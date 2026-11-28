"""委托请求整理与澄清：将用户支线疑问转为可编辑的结构化请求，最多澄清一次。"""

from __future__ import annotations

from collections.abc import Mapping
import re

from intentaware.nlp.errors import NlpError, NlpTimeoutError, NlpTransportError
from intentaware.nlp.fields import text_field

from .errors import DelegationError, DelegationNetworkError, DelegationTimeoutError
from .models import DelegationDraft
from .prompts import Prompt, load_prompt

FORMULATE_SCHEMA = {
    "type": "object",
    "required": ["question", "scope", "expected_output", "clarification_question"],
    "properties": {
        "question": {"type": "string", "minLength": 1},
        "scope": {"type": "string"},
        "expected_output": {"type": "string"},
        "clarification_question": {"type": "string"},
    },
}

_DEFAULT_SCOPE = "围绕问题本身，仅检索最多两份公开来源进行核对"
_DEFAULT_EXPECTED_OUTPUT = "简短结论、来源链接及未解决点"
_AMBIGUOUS_ZH = ("这个", "那个", "该工具", "该软件", "这款", "这种", "这方面", "它")
_AMBIGUOUS_EN = re.compile(r"\b(this|that|it|they|this tool|that tool)\b", re.IGNORECASE)


def _needs_local_clarification(question: str, note: str, clarification_answer: str, round_no: int) -> str:
    if round_no >= 1 or clarification_answer.strip() or note.strip():
        return ""
    compact = re.sub(r"\s+", "", question)
    if len(compact) < 6:
        return "请补充具体想查询的对象、工具名称或上下文，避免检索范围过宽。"
    if any(token in question for token in _AMBIGUOUS_ZH) or _AMBIGUOUS_EN.search(question):
        return "问题中包含“这个/它”等指代词，请补充具体的工具、文档或比较维度。"
    return ""


class LocalRequestFormulator:
    """离线请求整理器：不依赖网络，在无模型或回退时提供稳定整理与最多一次澄清。"""

    def draft(
        self,
        raw_question: str,
        *,
        note: str = "",
        goal_title: str = "",
        clarification_answer: str = "",
        clarification_round: int = 0,
    ) -> DelegationDraft:
        cleaned = raw_question.strip()
        if not cleaned:
            raise ValueError("请输入需要委托的问题。")

        answer_text = clarification_answer.strip()
        note_text = note.strip()
        question = f"{cleaned}（补充：{answer_text}）" if answer_text else cleaned

        if note_text:
            scope = f"结合补充说明「{note_text[:80]}」，核查最多两份公开来源"
        elif goal_title.strip():
            scope = f"围绕与「{goal_title.strip()[:40]}」相关的当前疑问，核查最多两份公开来源"
        else:
            scope = _DEFAULT_SCOPE

        clarification = _needs_local_clarification(
            cleaned, note_text, answer_text, clarification_round
        )
        return DelegationDraft(
            raw_question=cleaned,
            question=question,
            scope=scope,
            expected_output=_DEFAULT_EXPECTED_OUTPUT,
            clarification_question=clarification,
            clarification_round=clarification_round,
        )


class LlmRequestFormulator:
    """基于 LLM 的请求整理器：将问题整理为问题/范围/期望输出，关键歧义最多澄清一次。"""

    def __init__(
        self,
        client,
        *,
        prompt: Prompt | None = None,
        fallback: LocalRequestFormulator | None = None,
    ):
        self.client = client
        self.prompt = prompt or load_prompt("formulate_v1")
        self.fallback = fallback

    def draft(
        self,
        raw_question: str,
        *,
        note: str = "",
        goal_title: str = "",
        clarification_answer: str = "",
        clarification_round: int = 0,
    ) -> DelegationDraft:
        cleaned = raw_question.strip()
        if not cleaned:
            raise ValueError("请输入需要委托的问题。")

        allow_clarification = clarification_round < 1 and not clarification_answer.strip()
        system, user = self.prompt.render(
            {
                "goal_title": goal_title.strip() or "（未设置）",
                "raw_question": cleaned,
                "note": note.strip() or "（无）",
                "clarification_answer": clarification_answer.strip() or "（无）",
                "allow_clarification": "yes" if allow_clarification else "no",
            }
        )
        try:
            payload = self.client.complete_json(
                system=system, user=user, schema=FORMULATE_SCHEMA
            )
            return self._parse(
                payload,
                raw_question=cleaned,
                allow_clarification=allow_clarification,
                clarification_round=clarification_round,
            )
        except NlpTimeoutError as exc:
            if self.fallback is not None:
                return self.fallback.draft(
                    cleaned,
                    note=note,
                    goal_title=goal_title,
                    clarification_answer=clarification_answer,
                    clarification_round=clarification_round,
                )
            raise DelegationTimeoutError(str(exc)) from None
        except NlpTransportError as exc:
            if self.fallback is not None:
                return self.fallback.draft(
                    cleaned,
                    note=note,
                    goal_title=goal_title,
                    clarification_answer=clarification_answer,
                    clarification_round=clarification_round,
                )
            raise DelegationNetworkError(str(exc)) from None
        except NlpError as exc:
            if self.fallback is not None:
                return self.fallback.draft(
                    cleaned,
                    note=note,
                    goal_title=goal_title,
                    clarification_answer=clarification_answer,
                    clarification_round=clarification_round,
                )
            raise DelegationError(str(exc)) from None

    @staticmethod
    def _parse(
        payload: Mapping[str, object],
        *,
        raw_question: str,
        allow_clarification: bool,
        clarification_round: int,
    ) -> DelegationDraft:
        question = text_field(payload.get("question"), "question", limit=240)
        raw_scope = payload.get("scope")
        scope = raw_scope.strip()[:240] if isinstance(raw_scope, str) and raw_scope.strip() else _DEFAULT_SCOPE
        raw_output = payload.get("expected_output")
        expected_output = (
            raw_output.strip()[:200]
            if isinstance(raw_output, str) and raw_output.strip()
            else _DEFAULT_EXPECTED_OUTPUT
        )
        raw_clarification = payload.get("clarification_question")
        clarification = (
            raw_clarification.strip()[:200]
            if allow_clarification and isinstance(raw_clarification, str) and raw_clarification.strip()
            else ""
        )
        return DelegationDraft(
            raw_question=raw_question,
            question=question,
            scope=scope,
            expected_output=expected_output,
            clarification_question=clarification,
            clarification_round=clarification_round,
        )
