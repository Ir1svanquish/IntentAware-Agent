"""把一句话目标澄清为可执行的主任务与下一步。

输出 ``GoalClarification`` 而不是直接写库：是否采用由用户确认，低置信度时
界面应展示理由并要求补充信息，避免模型替用户编造范围。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from intentaware.contracts import Goal

from .errors import NlpResponseError
from .fields import text_field
from .prompts import Prompt, load_prompt

CLARIFY_SCHEMA = {
    "type": "object",
    "required": ["title", "next_step", "confidence", "rationale"],
    "properties": {
        "title": {"type": "string", "minLength": 2},
        "next_step": {"type": "string", "minLength": 2},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string", "minLength": 1},
    },
}

_CONFIDENCE = ("high", "medium", "low")


@dataclass(frozen=True)
class GoalClarification:
    title: str
    next_step: str
    confidence: str
    rationale: str

    @property
    def needs_confirmation(self) -> bool:
        """低置信度时界面应要求用户补充或修改，而不是直接采用。"""
        return self.confidence == "low"

    def as_goal(self) -> Goal:
        return Goal(title=self.title, next_step=self.next_step)


class LlmGoalClarifier:
    def __init__(self, client, *, prompt: Prompt | None = None):
        self.client = client
        self.prompt = prompt or load_prompt("clarify_v1")
        self.metadata = {
            "prompt": self.prompt.version,
            "model": getattr(client, "model", "unknown"),
        }

    def clarify(self, text: str) -> GoalClarification:
        text = text.strip()
        if not text:
            raise ValueError("请先写下一句目标描述。")
        system, user = self.prompt.render({"text": text})
        payload = self.client.complete_json(
            system=system, user=user, schema=CLARIFY_SCHEMA
        )
        return self._parse(payload)

    @staticmethod
    def _parse(payload: Mapping[str, object]) -> GoalClarification:
        confidence = payload.get("confidence")
        if not isinstance(confidence, str) or confidence not in _CONFIDENCE:
            raise NlpResponseError(f"模型返回了未知的置信度：{confidence!r}。")
        return GoalClarification(
            title=text_field(payload.get("title"), "title", limit=60),
            next_step=text_field(payload.get("next_step"), "next_step", limit=120),
            confidence=confidence,
            rationale=text_field(payload.get("rationale"), "rationale", limit=200),
        )
