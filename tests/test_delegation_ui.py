"""桌面端委托页面交互测试（offscreen）：整理请求、1 次澄清、编辑确认、检查点交付与门控。"""

import time
from threading import Event

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from intentaware.contracts import Condition, JobStatus
from intentaware.delegation import LiveDelegator, LlmRequestFormulator, MockRetriever, RetrievedDocument
from intentaware.delegation.demo import DemoDelegator
from intentaware.memory.store import SQLiteStore
from intentaware.nlp.llm import FakeLLMClient
from intentaware.session import DesktopSession
from intentaware.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["intentaware-delegation-ui", "-platform", "offscreen"])


def _wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), "timed out waiting for Qt event loop"


def test_delegation_formulate_clarify_confirm_and_checkpoint_delivery(app, tmp_path):
    docs = [
        RetrievedDocument(
            source_id="S1",
            title="Obsidian 官方说明",
            url="https://obsidian.md/pricing",
            snippet="个人免费使用",
            excerpt="Obsidian 支持本地 Markdown 文件，个人使用免费。",
        )
    ]
    llm = FakeLLMClient(
        [
            {
                "answer": "Obsidian 个人使用免费，且基于本地 Markdown 文件。",
                "citations": [{"source_id": "S1", "quote": "个人使用免费"}],
                "unresolved": ["多人实时协作需另行配置同步方案。"],
            }
        ]
    )
    delegator = LiveDelegator(llm, MockRetriever(docs))
    session = DesktopSession(SQLiteStore(tmp_path / "ui.sqlite3"), delegator=delegator, condition=Condition.D)
    window = MainWindow(session)
    window.show()
    try:
        assert window.delegation_badge.text() == "公开检索 · LLM"

        window.correction_button.click()
        window.goal_input.setText("整理团队知识库方案")
        window.next_step_input.setText("对比备选工具")
        window.save_goal_button.click()

        window.delegation_nav.click()
        window.question_input.setText("这个工具免费吗")
        window.formulate_button.click()

        assert window.draft_editor.isVisible()
        assert window.clarification_box.isVisible()

        window.clarification_input.setText("指的是 Obsidian")
        window.apply_clarification_button.click()
        assert not window.clarification_box.isVisible()
        assert "Obsidian" in window.draft_question_input.text()

        window.draft_scope_input.setText("仅核对个人与团队定价及 Markdown 支持")
        window.confirm_draft_button.click()
        assert not window.draft_editor.isVisible()
        assert len(session.jobs) == 1

        job = session.jobs[0]
        _wait_until(lambda: job.status != JobStatus.RUNNING)
        assert job.status == JobStatus.READY
        assert "个人使用免费" not in window.job_result.toPlainText()

        window.checkpoint_label_input.setText("写完工具对比表")
        window.checkpoint_button.click()
        assert job.status == JobStatus.DELIVERED
        assert "个人使用免费" in window.job_result.toPlainText()
        assert "https://obsidian.md/pricing" in window.job_result.toPlainText()
        assert window.checkpoint_label_input.text() == ""
        assert any(
            e.name == "checkpoint_reached" and e.details.get("has_label") is True
            for e in session.events
        )
    finally:
        window.close()


def test_offline_draft_and_delivery_keep_the_question_separate_from_the_main_task(app, tmp_path):
    session = DesktopSession(
        SQLiteStore(tmp_path / "offline.sqlite3"),
        delegator=DemoDelegator(delay_seconds=0), condition=Condition.D,
    )
    session.set_goal("准备演示讲稿", "完善研究方法章节")
    question = "如何让 argparse 的可选参数变成必填？"
    window = MainWindow(session)
    window.show()
    try:
        window.delegation_nav.click()
        window.question_input.setText(question)
        window.formulate_button.click()
        scope = window.draft_scope_input.text()
        assert "准备演示讲稿" not in scope
        assert "公开来源" not in scope
        assert "离线" in scope

        window.confirm_draft_button.click()
        _wait_until(lambda: session.jobs[0].status == JobStatus.READY)
        assert question not in window.job_result.toPlainText()
        window.checkpoint_button.click()
        assert session.jobs[0].status == JobStatus.DELIVERED
        result = window.job_result.toPlainText()
        assert result.count(question) == 1
        assert "已接收问题：问题：" not in result and "问题：问题：" not in result
        assert window.job_list.item(0).text() == f"已交付   {question}"
    finally:
        window.close()


@pytest.mark.parametrize("condition, completion_status", [
    (Condition.I, JobStatus.DELIVERED),
    (Condition.D, JobStatus.READY),
])
def test_live_draft_stays_responsive_and_defers_search_until_confirmation(
    app, tmp_path, condition, completion_status
):
    started, release = Event(), Event()
    ticks = []

    class BlockingModel(FakeLLMClient):
        def complete_json(self, **kwargs):
            started.set()
            assert release.wait(4)
            return super().complete_json(**kwargs)

    draft_client = BlockingModel([{
        "question": "When does the meeting start?",
        "scope": "meeting schedule", "expected_output": "time", "clarification_question": "",
    }])
    retriever = MockRetriever([RetrievedDocument(
        "S1", "Schedule", "https://example.org/schedule", "", "The meeting starts at 10."
    )])
    delegator = LiveDelegator(FakeLLMClient([{
        "citations": [{"source_id": "S1", "quote": "The meeting starts at 10."}],
        "unresolved": [],
    }]), retriever)
    session = DesktopSession(
        SQLiteStore(tmp_path / "live.sqlite3"), delegator=delegator, condition=condition
    )
    session.set_goal("private test goal", "plan the meeting")
    session.add_detour("What time is the meeting?", purpose="private saved note purpose")
    window = MainWindow(session, formulator=LlmRequestFormulator(draft_client))
    window.show()
    try:
        window.detours_nav.click()
        window.detour_list.setCurrentRow(0)
        window.delegate_detour_button.click()
        assert window.delegation_nav.isChecked()
        assert not window.submit_button.isVisible()
        assert window.question_input.text() == "What time is the meeting?"
        assert not started.is_set() and not retriever.calls
        QTimer.singleShot(20, lambda: ticks.append(True))
        QTest.keyClick(window.question_input, Qt.Key.Key_Return)
        _wait_until(lambda: started.is_set() and ticks)
        assert not window.confirm_draft_button.isEnabled()
        assert not session.jobs and not retriever.calls
        window.workbench_nav.click()
        release.set()
        _wait_until(window.confirm_draft_button.isEnabled)
        assert not session.jobs and not retriever.calls
        assert "What time is the meeting?" in draft_client.calls[0]["user"]
        assert "private test goal" not in draft_client.calls[0]["user"]
        assert "private saved note purpose" not in draft_client.calls[0]["user"]

        window.delegation_nav.click()
        window.confirm_draft_button.click()
        _wait_until(lambda: session.jobs[0].status == completion_status)
        assert retriever.calls[0]["query"] == "When does the meeting start?"
        if condition == Condition.D:
            assert "The meeting starts at 10." not in window.job_result.toPlainText()
            window.checkpoint_button.click()
        assert "[来源 1] The meeting starts at 10." in window.job_result.toPlainText()
    finally:
        release.set()
        window.close()
