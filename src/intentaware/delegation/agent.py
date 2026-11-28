"""D 模块核心后台委托 Agent：串联有界检索、证据综合回答与引用核验。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError
from contextlib import nullcontext
from threading import Event, Lock
import time

from intentaware.localization import feedback_prompt, tr
from intentaware.contracts import DelegationResult
from intentaware.nlp.config import LlmConfig
from intentaware.nlp.errors import NlpError, NlpResponseError, NlpTimeoutError, NlpTransportError
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
    "required": ["citations", "unresolved"],
    "properties": {
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
        raise CancelledError(tr("委托任务已取消。"))


def run_delegation(delegator, question: str, cancel: Event) -> tuple[DelegationResult, dict]:
    run_with_metrics = getattr(delegator, "run_with_metrics", None)
    if callable(run_with_metrics):
        return run_with_metrics(question, cancel)
    return delegator.run(question, cancel), {}


def _format_sources_block(documents: list[RetrievedDocument]) -> str:
    blocks = []
    for doc in documents[:2]:
        blocks.append(
            tr("[{0}] 标题：{1}\n链接：{2}\n正文摘录：{3}", doc.source_id, doc.title, doc.url, doc.excerpt)
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
        self._client_lock = nullcontext() if isinstance(llm, LlmConfig) or callable(llm) else Lock()

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

    def _new_client(self):
        if isinstance(self._llm, LlmConfig):
            return OpenAICompatibleClient(self._llm)
        if callable(self._llm):
            return self._llm()
        return self._llm

    def run(self, question: str, cancel: Event) -> DelegationResult:
        result, _ = self.run_with_metrics(question, cancel)
        return result

    def run_with_metrics(self, question: str, cancel: Event) -> tuple[DelegationResult, dict]:
        _check_cancel(cancel)
        draft = DelegationDraft.parse_question(question)
        started = time.perf_counter()

        docs = self.retriever.retrieve(
            draft.question,
            max_sources=self.config.max_sources,
            cancel=cancel,
        )
        _check_cancel(cancel)
        docs = docs[:min(self.config.max_sources, 2)]
        if not docs:
            raise DelegationRetrievalError(tr("未检索到相关的公开来源，暂不生成无依据回答。"))

        system, user = self.prompt.render(
            {
                "question": draft.question,
                "scope": draft.scope or tr("围绕问题本身，基于有限公开来源作答"),
                "expected_output": draft.expected_output or tr("简短结论、依据及未解决点"),
                "sources_block": _format_sources_block(docs),
            }
        )

        client = self._new_client()
        try:
            with self._client_lock:
                _check_cancel(cancel)
                payload = client.complete_json(system=feedback_prompt(system), user=user, schema=ANSWER_SCHEMA)
                last_usage = getattr(client, "last_usage", None)
                usage = dict(last_usage) if isinstance(last_usage, dict) else {}
            _check_cancel(cancel)
            citations, unresolved = self._parse_payload(payload)
        except NlpTimeoutError as exc:
            raise DelegationTimeoutError(str(exc)) from None
        except NlpTransportError as exc:
            raise DelegationNetworkError(str(exc)) from None
        except NlpError as exc:
            raise DelegationError(str(exc)) from None
        report = self.verifier.verify(citations, docs)
        if not report.passed:
            raise DelegationVerificationError(tr("回答引用未通过公开来源核验，已拦截无依据输出。"))

        source_numbers = {source.url: index for index, source in enumerate(report.verified_sources, start=1)}
        document_urls = {doc.source_id: doc.url for doc in docs}
        excerpts = "\n".join(
            tr("- [来源 {0}] {1}", source_numbers[document_urls[quote.source_id]], quote.quote)
            for quote in report.verified_quotes
        )
        sections = [tr("已核对的原文摘录\n{0}", excerpts)]
        if unresolved:
            unresolved_lines = "\n".join(f"- {item}" for item in unresolved)
            sections.append(tr("未解决的部分（模型整理）\n{0}", unresolved_lines))

        if report.dropped_reasons:
            sections.append(tr("引用核验说明\n- 已过滤 {0} 条未能核实的引用。", len(report.dropped_reasons)))

        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        metrics: dict[str, object] = {
            "latency_ms": latency_ms,
            "sources_count": len(report.verified_sources),
            "retrieved_count": len(docs),
            "dropped_citations": len(report.dropped_reasons),
            "prompt": self.prompt.version,
            "model": getattr(client, "model", self._metadata["model"]),
        }
        if usage:
            metrics["usage"] = usage

        return DelegationResult(
            answer="\n\n".join(sections),
            sources=report.verified_sources,
        ), metrics

    @staticmethod
    def _parse_payload(
        payload: Mapping[str, object],
    ) -> tuple[list[CitationClaim], list[str]]:
        raw_citations = payload.get("citations")
        if not isinstance(raw_citations, list):
            raise NlpResponseError(tr("模型返回的 citations 必须是数组。"))
        citations: list[CitationClaim] = []
        for item in raw_citations[:4]:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            quote = str(item.get("quote") or "").strip()
            if source_id and quote:
                citations.append(CitationClaim(source_id=source_id, quote=quote))

        raw_unresolved = payload.get("unresolved")
        if not isinstance(raw_unresolved, list):
            raise NlpResponseError(tr("模型返回的 unresolved 必须是数组。"))
        unresolved = [
            item.strip()[:200]
            for item in raw_unresolved
            if isinstance(item, str) and item.strip()
        ]
        return citations, unresolved
