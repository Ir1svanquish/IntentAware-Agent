"""请求整理、结构解析与最多一次澄清规则测试（全部离线）。"""

import pytest

from intentaware.delegation import (
    DelegationDraft,
    DelegationNetworkError,
    DelegationTimeoutError,
    LlmRequestFormulator,
    LocalRequestFormulator,
)
from intentaware.nlp.errors import NlpTimeoutError, NlpTransportError
from intentaware.nlp.llm import FakeLLMClient


def test_draft_format_and_parse_roundtrip():
    draft = DelegationDraft(
        raw_question="这个工具能否替代我们现在的软件",
        question="Obsidian 能否替代 Notion 进行团队笔记协作？",
        scope="只核对文件格式兼容性与免费版限制",
        expected_output="3 条以内对比结论与未解决点",
    )
    formatted = draft.format_question()
    assert "问题：Obsidian 能否替代 Notion 进行团队笔记协作？" in formatted
    assert "处理范围：只核对文件格式兼容性与免费版限制" in formatted
    assert "期望输出：3 条以内对比结论与未解决点" in formatted

    parsed = DelegationDraft.parse_question(formatted)
    assert parsed.question == draft.question
    assert parsed.scope == draft.scope
    assert parsed.expected_output == draft.expected_output


def test_parse_plain_question():
    parsed = DelegationDraft.parse_question("Python argparse 怎么设置必填参数？")
    assert parsed.question == "Python argparse 怎么设置必填参数？"
    assert parsed.scope == ""
    assert parsed.expected_output == ""


def test_local_formulator_clarifies_once_and_caps_at_one_round():
    formulator = LocalRequestFormulator()
    first = formulator.draft("这个工具能用吗", goal_title="完成课程项目")
    assert first.needs_clarification is True
    assert first.clarification_question

    second = formulator.draft(
        first.raw_question,
        goal_title="完成课程项目",
        clarification_answer="指的是 DuckDuckGo 网页检索",
        clarification_round=1,
    )
    assert second.needs_clarification is False
    assert second.clarification_question == ""
    assert "DuckDuckGo" in second.question


def test_local_formulator_rejects_empty_question():
    with pytest.raises(ValueError):
        LocalRequestFormulator().draft("   ")


def test_llm_formulator_enforces_single_clarification_cap():
    client = FakeLLMClient(
        [
            {
                "question": "确认目标工具与约束条件",
                "scope": "比较文件兼容性与免费版限制",
                "expected_output": "简短对比",
                "clarification_question": "请问“这个工具”具体指哪款软件？",
            },
            {
                "question": "Figma 免费版能否满足团队导出 PDF 与矢量图需求？",
                "scope": "仅核对免费版导出限制与格式支持",
                "expected_output": "3 条要点结论",
                # 即使模型在第二轮又返回了澄清问题，也必须被拦截置空
                "clarification_question": "还需要确认操作系统吗？",
            },
        ]
    )
    formulator = LlmRequestFormulator(client)

    round0 = formulator.draft("这个工具能替代吗", goal_title="设计展示海报")
    assert round0.needs_clarification is True
    assert "哪款软件" in round0.clarification_question

    round1 = formulator.draft(
        "这个工具能替代吗",
        goal_title="设计展示海报",
        clarification_answer="指的是 Figma",
        clarification_round=1,
    )
    assert round1.needs_clarification is False
    assert round1.clarification_question == ""
    assert "Figma" in round1.question


def test_llm_formulator_fallback_and_error_translation():
    failing = FakeLLMClient([NlpTimeoutError("请求超时")])
    with pytest.raises(DelegationTimeoutError):
        LlmRequestFormulator(failing).draft("SQLite WAL 模式适合什么场景？")

    transport_failing = FakeLLMClient([NlpTransportError("网络中断")])
    with pytest.raises(DelegationNetworkError):
        LlmRequestFormulator(transport_failing).draft("SQLite WAL 模式适合什么场景？")

    with_fallback = LlmRequestFormulator(
        FakeLLMClient([NlpTimeoutError("请求超时")]),
        fallback=LocalRequestFormulator(),
    )
    draft = with_fallback.draft("SQLite WAL 模式适合什么场景？")
    assert "SQLite WAL" in draft.question
    assert draft.scope


def test_llm_formulator_handles_blank_question_in_payload():
    from intentaware.delegation import DelegationError

    bad_payload = {
        "question": "   ",
        "scope": "scope",
        "expected_output": "output",
        "clarification_question": "",
    }
    with pytest.raises(DelegationError):
        LlmRequestFormulator(FakeLLMClient([dict(bad_payload)])).draft("SQLite WAL 模式适合什么场景？")

    with_fallback = LlmRequestFormulator(
        FakeLLMClient([dict(bad_payload)]),
        fallback=LocalRequestFormulator(),
    )
    draft = with_fallback.draft("SQLite WAL 模式适合什么场景？")
    assert "SQLite WAL" in draft.question
