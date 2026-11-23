"""LLM 分类器的映射、Prompt 内容与回退行为，全部使用假客户端。"""

import pytest

from intentaware.contracts import ActivityContext, ActivityLabel, Goal
from intentaware.nlp.classifier import LlmActivityClassifier
from intentaware.nlp.demo import DemoClassifier
from intentaware.nlp.errors import NlpResponseError, NlpTransportError
from intentaware.nlp.llm import FakeLLMClient

GOAL = Goal("完成论文方法章节", "整理三篇文献并写提纲")


def context(activity="前台窗口：Google Chrome｜Attention Is All You Need.pdf", progress="已读完两篇"):
    return ActivityContext(goal=GOAL, activity=activity, progress=progress)


def classifier_returning(label="necessary_preparation", **fields):
    payload = {
        "label": label,
        "reason": "正在阅读与下一步相关的文献。",
        "suggested_next_step": "读完第三篇后整理方法章节提纲。",
    }
    payload.update(fields)
    return LlmActivityClassifier(FakeLLMClient([payload]))


@pytest.mark.parametrize("label", [item.value for item in ActivityLabel])
def test_every_shared_label_round_trips(label):
    result = classifier_returning(label).classify(context())

    assert isinstance(result.label, ActivityLabel)
    assert result.label.value == label
    assert result.reason
    assert result.suggested_next_step


def test_prompt_carries_goal_progress_and_observation_source():
    client = FakeLLMClient([{"label": "unclear", "reason": "信息不足", "suggested_next_step": "补充活动"}])
    classifier = LlmActivityClassifier(client)

    classifier.classify(context())

    user = client.calls[0]["user"]
    assert GOAL.title in user
    assert GOAL.next_step in user
    assert "已读完两篇" in user
    assert "窗口观察" in user
    assert "Attention Is All You Need.pdf" in user


def test_manual_activity_is_marked_as_user_description():
    client = FakeLLMClient([{"label": "direct_progress", "reason": "在写正文", "suggested_next_step": "继续写"}])
    LlmActivityClassifier(client).classify(context(activity="正在撰写方法章节", progress=""))

    user = client.calls[0]["user"]
    assert "用户描述" in user
    assert "（未填写）" in user


@pytest.mark.parametrize(
    "payload",
    [
        {"label": "unknown", "reason": "理由", "suggested_next_step": "下一步"},
        {"label": "unclear", "reason": "  ", "suggested_next_step": "下一步"},
        {"label": "unclear", "reason": "理由", "suggested_next_step": ""},
        {"label": "unclear", "reason": "理由"},
    ],
)
def test_invalid_payload_is_a_response_error(payload):
    classifier = LlmActivityClassifier(FakeLLMClient([payload]))
    with pytest.raises(NlpResponseError):
        classifier.classify(context())


def test_overlong_reason_is_truncated_instead_of_rejected():
    result = classifier_returning(reason="很长的理由" * 100).classify(context())

    assert len(result.reason) <= 160
    assert result.reason.endswith("…")


def test_empty_activity_is_rejected_before_calling_the_model():
    client = FakeLLMClient([])
    with pytest.raises(ValueError):
        LlmActivityClassifier(client).classify(context(activity="   "))
    assert client.calls == []


def test_fallback_classifier_keeps_user_visible_trace_of_degradation():
    client = FakeLLMClient([NlpTransportError("无法连接模型服务")])
    classifier = LlmActivityClassifier(client, fallback=DemoClassifier())

    result = classifier.classify(context(activity="正在撰写论文正文"))

    assert result.label is ActivityLabel.DIRECT_PROGRESS
    assert result.reason.startswith("回退本地规则：")


def test_metadata_records_prompt_version_and_model():
    classifier = classifier_returning()
    assert classifier.metadata["prompt"].startswith("classify_v1@")
    assert classifier.metadata["model"] == "fake-model"
