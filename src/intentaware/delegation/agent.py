"""D 模块核心后台委托 Agent：串联有界检索、证据综合回答与引用核验。"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError
from threading import Event, Lock
import time

from intentaware.contracts import DelegationResult
from intentaware.nlp.config import LlmConfig
from intentaware.nlp.errors import NlpError, NlpResponseError, NlpTimeoutError, NlpTransportError
from intentaware.nlp.fields import text_field
from intentaware.nlp.llm import OpenAICompatibleClient

from .config import DelegationConfig
from .errors import (
    DelegationError,
    DelegationNetworkError,
    DelegationRetrievalError,
    DelegationTimeoutError,
    DelegationVerificationError,
)
from .models import CitationClaim, DelegationDraft, RetrievedDocument
from .prompts import Prompt, load_prompt
from .retriever import Retriever
from .verifier import CitationVerifier

ANSWER_SCHEMA = {
    "type": "object",
    "required": ["answer", "citations", "unresolved"],
    "properties": {
        "answer": {"type": "string", "minLength": 2},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_id", "quote"],
                "properties": {
                    "source_id": {"type": "string", "minLength": 1},
                    "quote": {"type": "string", "minLength": 1},
                },
            },
        },
        "unresolved": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def _check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise CancelledError("委托任务已取消。")


def _format_sources_block(documents: list[RetrievedDocument]) -> str:
    blocks = []
    for doc in documents[:2]:
        blocks.append(
            f"[{doc.source_id}] 标题：{doc.title}\n"
            f"链接：{doc.url}\n"
            f"正文摘录：{doc.excerpt}"
        )
    return "\n\n".join(blocks)


class LiveDelegator:
    """实现 ``Delegator`` 协议：检索最多两份公开来源，生成带未解决点与核验引用的答案。"""

    def __init__(
        self,
        llm: LlmConfig | Callable[[], object] | object,
        retriever: Retriever,
        *,
        config: DelegationConfig | None = None,
        prompt: Prompt | None = None,
        verifier: CitationVerifier | None = None,
    ):
        self._llm = llm
        self.retriever = retriever
        self.config = config or DelegationConfig()
        self.prompt = prompt or load_prompt("answer_v1")
        self.verifier = verifier or CitationVerifier()
        self._lock = Lock()
        self._metrics_by_question: dict[str, deque[dict[str, object]]] = {}
        self._last_metrics: dict[str, object] = {}

        if isinstance(llm, LlmConfig):
            model_name = llm.model
        else:
            model_name = getattr(llm, "model", "custom")

        self._metadata: dict[str, object] = {
            "prompt": self.prompt.version,
            "model": model_name,
            "retriever": type(retriever).__name__,
            "search_provider": self.config.search_provider,
            "max_sources": self.config.max_sources,
        }

    @property
    def metadata(self) -> dict[str, object]:
        """静态配置摘要，供会话启动及事件记录使用。"""
        return dict(self._metadata)

    @property
    def last_metrics(self) -> dict[str, object]:
        with self._lock:
            return dict(self._last_metrics)

    def peek_job_metrics(self, question: str) -> dict[str, object]:
        """按问题文本读取该次执行的延迟、Token 与来源数，不移除缓存。"""
        with self._lock:
            queue = self._metrics_by_question.get(question.strip())
            return dict(queue[0]) if queue else {}

    def pop_job_metrics(self, question: str) -> dict[str, object]:
        """按问题文本取出该次执行的延迟、Token 与来源数，线程安全（FIFO）。"""
        key = question.strip()
        with self._lock:
            queue = self._metrics_by_question.get(key)
            if not queue:
                return {}
            metrics = dict(queue.popleft())
            if not queue:
                self._metrics_by_question.pop(key, None)
            return metrics

    def _new_client(self):
        if isinstance(self._llm, LlmConfig):
            return OpenAICompatibleClient(self._llm)
        if callable(self._llm):
            return self._llm()
        return self._llm

    def run(self, question: str, cancel: Event) -> DelegationResult:
        _check_cancel(cancel)
        draft = DelegationDraft.parse_question(question)
        started = time.perf_counter()

        docs = self.retriever.retrieve(
            draft.question,
            max_sources=self.config.max_sources,
            cancel=cancel,
        )
        _check_cancel(cancel)
        docs = docs[:2]
        if not docs:
            raise DelegationRetrievalError("未检索到相关的公开来源，暂不生成无依据回答。")

        system, user = self.prompt.render(
            {
                "question": draft.question,
                "scope": draft.scope or "围绕问题本身，基于有限公开来源作答",
                "expected_output": draft.expected_output or "简短结论、依据及未解决点",
                "sources_block": _format_sources_block(docs),
            }
        )

        client = self._new_client()
        try:
            payload = client.complete_json(system=system, user=user, schema=ANSWER_SCHEMA)
            _check_cancel(cancel)
            answer_body, citations, unresolved = self._parse_payload(payload)
        except NlpTimeoutError as exc:
            raise DelegationTimeoutError(str(exc)) from None
        except NlpTransportError as exc:
            raise DelegationNetworkError(str(exc)) from None
        except NlpError as exc:
            raise DelegationError(str(exc)) from None
        report = self.verifier.verify(citations, docs)
        if not report.passed:
            raise DelegationVerificationError("回答引用未通过公开来源核验，已拦截无依据输出。")

        sections = [answer_body]
        if unresolved:
            unresolved_lines = "\n".join(f"- {item}" for item in unresolved)
            sections.append(f"未解决的部分\n{unresolved_lines}")
        else:
            sections.append("未解决的部分\n- 当前检索到的有限公开来源已覆盖主要问题；如需更深入场景可继续补充条件。")

        if report.dropped_reasons:
            sections.append(f"引用核验说明\n- 已过滤 {len(report.dropped_reasons)} 条未能核实的引用。")

        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        usage = getattr(client, "last_usage", None)
        metrics: dict[str, object] = {
            "latency_ms": latency_ms,
            "sources_count": len(report.verified_sources),
            "retrieved_count": len(docs),
            "dropped_citations": len(report.dropped_reasons),
            "prompt": self.prompt.version,
            "model": getattr(client, "model", self._metadata["model"]),
        }
        if isinstance(usage, dict) and usage:
            metrics["usage"] = dict(usage)

        with self._lock:
            self._last_metrics = metrics
            key = question.strip()
            queue = self._metrics_by_question.setdefault(key, deque())
            queue.append(metrics)
            while len(self._metrics_by_question) > 64:
                oldest_key = next(iter(self._metrics_by_question))
                self._metrics_by_question.pop(oldest_key, None)

        return DelegationResult(
            answer="\n\n".join(sections),
            sources=report.verified_sources,
        )

    @staticmethod
    def _parse_payload(
        payload: Mapping[str, object],
    ) -> tuple[str, list[CitationClaim], list[str]]:
        answer = text_field(payload.get("answer"), "answer", limit=1200)
        raw_citations = payload.get("citations")
        if not isinstance(raw_citations, list):
            raise NlpResponseError("模型返回的 citations 必须是数组。")
        citations: list[CitationClaim] = []
        for item in raw_citations:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            quote = str(item.get("quote") or "").strip()
            if source_id and quote:
                citations.append(CitationClaim(source_id=source_id, quote=quote))

        raw_unresolved = payload.get("unresolved")
        if not isinstance(raw_unresolved, list):
            raise NlpResponseError("模型返回的 unresolved 必须是数组。")
        unresolved = [
            item.strip()[:200]
            for item in raw_unresolved
            if isinstance(item, str) and item.strip()
        ]
        return answer, citations, unresolved
