"""目标澄清、命令行入口以及会话事件中的可复现元数据。"""

import json

import pytest

from intentaware.memory.store import SQLiteStore
from intentaware.nlp import clarify as clarify_module
from intentaware.nlp.classifier import LlmActivityClassifier
from intentaware.nlp.errors import NlpConfigError, NlpResponseError
from intentaware.nlp.goal import GoalClarification, LlmGoalClarifier
from intentaware.nlp.llm import FakeLLMClient
from intentaware.session import DesktopSession

PAYLOAD = {
    "title": "完成论文方法章节",
    "next_step": "整理三篇文献并写提纲",
    "confidence": "high",
    "rationale": "用户给出了明确交付物与下一步。",
}


def clarifier(payload=None):
    return LlmGoalClarifier(FakeLLMClient([dict(PAYLOAD if payload is None else payload)]))


def test_clarification_maps_json_to_shared_goal_shape():
    result = clarifier().clarify("我要写论文的方法章节，先整理文献")

    assert isinstance(result, GoalClarification)
    assert result.title == "完成论文方法章节"
    assert result.next_step == "整理三篇文献并写提纲"
    assert result.needs_confirmation is False
    goal = result.as_goal()
    assert (goal.title, goal.next_step) == (result.title, result.next_step)


def test_low_confidence_requires_user_confirmation():
    result = clarifier({**PAYLOAD, "confidence": "low", "rationale": "缺少截止时间和交付格式。"}).clarify(
        "搞一下论文"
    )
    assert result.needs_confirmation is True
    assert "缺少" in result.rationale


def test_prompt_contains_user_text_and_anti_fabrication_rule():
    client = FakeLLMClient([dict(PAYLOAD)])
    LlmGoalClarifier(client).clarify("下周三前交论文初稿")

    call = client.calls[0]
    assert "下周三前交论文初稿" in call["user"]
    assert "不要编造" in call["system"]


def test_empty_input_is_rejected_before_any_request():
    client = FakeLLMClient([])
    with pytest.raises(ValueError):
        LlmGoalClarifier(client).clarify("   ")
    assert client.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {**PAYLOAD, "confidence": "certain"},
        {**PAYLOAD, "title": ""},
        {**PAYLOAD, "next_step": 3},
        {"title": "只有标题"},
    ],
)
def test_invalid_payloads_raise_response_error(payload):
    with pytest.raises(NlpResponseError):
        clarifier(payload).clarify("写论文")


def test_overlong_title_is_truncated_to_the_documented_limit():
    result = clarifier({**PAYLOAD, "title": "很长的标题" * 50}).clarify("写论文")
    assert len(result.title) == 60
    assert result.title.endswith("…")


def test_clarifier_metadata_records_prompt_version_and_model():
    metadata = clarifier().metadata
    assert metadata["prompt"].startswith("clarify_v1@")
    assert metadata["model"] == "fake-model"


def test_cli_prints_json_for_scripting(capsys):
    code = clarify_module.main(["--json", "写论文"], clarifier=clarifier())

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == PAYLOAD["title"]
    assert payload["confidence"] == "high"


def test_cli_prints_human_readable_summary_and_low_confidence_hint(capsys):
    low = {**PAYLOAD, "confidence": "low"}
    code = clarify_module.main(["把论文弄一下"], clarifier=clarifier(low))

    assert code == 0
    out = capsys.readouterr().out
    assert "主任务：完成论文方法章节" in out
    assert "下一步：整理三篇文献并写提纲" in out
    assert "补充交付物" in out


def test_cli_reports_missing_configuration(monkeypatch, capsys):
    def fail(env=None):
        raise NlpConfigError("缺少 INTENTAWARE_LLM_API_KEY")

    monkeypatch.setattr(clarify_module, "build_clarifier", fail)

    assert clarify_module.main(["写论文"]) == 2
    assert "配置错误" in capsys.readouterr().err


def test_session_events_record_model_and_prompt_version(tmp_path):
    classifier = LlmActivityClassifier(
        FakeLLMClient(
            [
                {
                    "label": "direct_progress",
                    "reason": "正在撰写正文。",
                    "suggested_next_step": "继续写提纲。",
                }
            ]
        )
    )
    session = DesktopSession(SQLiteStore(tmp_path / "nlp.sqlite3"), classifier=classifier)
    try:
        session.set_goal("完成论文", "整理文献")
        session.analyze("正在撰写论文正文")
        events = {event.name: event for event in session.events}

        assert events["session_started"].details["model"] == "fake-model"
        classified = events["activity_classified"]
        assert classified.details["prompt"].startswith("classify_v1@")
        assert classified.details["model"] == "fake-model"
        assert classified.details["classifier"] == "LlmActivityClassifier"
    finally:
        session.close()
