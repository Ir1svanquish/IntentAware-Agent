"""可替换的活动分类与目标澄清模块。

- ``LocalActivityClassifier`` / ``LocalTaskRecognizer``：完全离线的本地规则。
- ``LlmActivityClassifier`` / ``LlmGoalClarifier``：通过 OpenAI 兼容接口调用模型。
- ``DemoClassifier``：历史关键词演示实现。

两种分类器都实现 ``contracts.interfaces.Classifier``，可注入 ``DesktopSession``。
"""

from .classifier import LlmActivityClassifier
from .config import LlmConfig
from .demo import DemoClassifier
from .errors import (
    NlpConfigError,
    NlpError,
    NlpResponseError,
    NlpTimeoutError,
    NlpTransportError,
)
from .goal import GoalClarification, LlmGoalClarifier
from .llm import FakeLLMClient, LLMClient, OpenAICompatibleClient
from .local import LocalActivityClassifier, LocalTaskRecognizer

__all__ = [
    "DemoClassifier",
    "FakeLLMClient",
    "GoalClarification",
    "LLMClient",
    "LlmActivityClassifier",
    "LlmConfig",
    "LlmGoalClarifier",
    "LocalActivityClassifier",
    "LocalTaskRecognizer",
    "NlpConfigError",
    "NlpError",
    "NlpResponseError",
    "NlpTimeoutError",
    "NlpTransportError",
    "OpenAICompatibleClient",
]
