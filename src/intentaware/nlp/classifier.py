"""用 LLM 完成活动四分类，输出仍是共享结构 ``Classification``。

窗口标题只作为“可能的工作上下文”传给模型；Prompt 明确要求不得据此推断进度。
网络或模型失败时，可以选择回退到本地规则，并在理由中标注，避免界面直接中断。
"""

from __future__ import annotations

from collections.abc import Mapping

from intentaware.localization import feedback_prompt, tr
from intentaware.contracts import ActivityContext, ActivityLabel, Classification

from .errors import NlpError, NlpResponseError
from .fields import text_field
from .local import observation_payload
from .prompts import Prompt, load_prompt

CLASSIFY_SCHEMA = {
    "type": "object",
    "required": ["label", "reason", "suggested_next_step"],
    "properties": {
        "label": {"type": "string", "enum": [item.value for item in ActivityLabel]},
        "reason": {"type": "string", "minLength": 1},
        "suggested_next_step": {"type": "string", "minLength": 1},
    },
}

_FIELD_LIMIT = 160


class LlmActivityClassifier:
    """实现 ``Classifier`` 协议，可直接注入 ``DesktopSession``。"""

    def __init__(
        self,
        client,
        *,
        prompt: Prompt | None = None,
        fallback=None,
    ):
        self.client = client
        self.prompt = prompt or load_prompt("classify_v1")
        self.fallback = fallback
        self._metadata = {
            "prompt": self.prompt.version,
            "model": getattr(client, "model", "unknown"),
        }

    @property
    def metadata(self) -> dict:
        """基础配置 + 最近一次调用的用量与耗时，由会话写入事件。"""
        details = dict(self._metadata)
        usage = getattr(self.client, "last_usage", None)
        if isinstance(usage, dict) and usage:
            details["usage"] = dict(usage)
        latency = getattr(self.client, "last_latency_ms", None)
        if isinstance(latency, (int, float)):
            details["latency_ms"] = round(float(latency), 1)
        return details

    def classify(self, context: ActivityContext) -> Classification:
        if not context.activity.strip():
            raise ValueError(tr("活动描述不能为空。"))
        try:
            return self._classify(context)
        except NlpError:
            if self.fallback is None:
                raise
            result = self.fallback.classify(context)
            return Classification(
                result.label,
                tr("回退本地规则：{0}", result.reason),
                result.suggested_next_step,
            )

    def _classify(self, context: ActivityContext) -> Classification:
        system, user = self.prompt.render(self._values(context))
        payload = self.client.complete_json(
            system=feedback_prompt(system), user=user, schema=CLASSIFY_SCHEMA
        )
        return self._parse(payload)

    @staticmethod
    def _values(context: ActivityContext) -> Mapping[str, str]:
        activity = context.activity.strip()
        return {
            "goal_title": context.goal.title.strip() or tr("（未填写）"),
            "goal_next_step": context.goal.next_step.strip() or tr("（未填写）"),
            "progress": context.progress.strip() or tr("（未填写）"),
            "source": tr("窗口观察") if observation_payload(activity) is not None else tr("用户描述"),
            "activity": activity,
        }

    @staticmethod
    def _parse(payload: Mapping[str, object]) -> Classification:
        raw_label = payload.get("label")
        if not isinstance(raw_label, str):
            raise NlpResponseError(tr("模型返回的 label 为空或不是字符串。"))
        try:
            label = ActivityLabel(raw_label)
        except ValueError:
            raise NlpResponseError(tr("模型返回了未知的活动类别：{0!r}。", raw_label)) from None
        return Classification(
            label,
            text_field(payload.get("reason"), "reason", limit=_FIELD_LIMIT),
            text_field(
                payload.get("suggested_next_step"),
                "suggested_next_step",
                limit=_FIELD_LIMIT,
            ),
        )
