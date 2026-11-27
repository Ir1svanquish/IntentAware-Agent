"""桌面端委托页面交互测试（offscreen）：整理请求、1 次澄清、编辑确认、检查点交付与门控。"""

import time

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from intentaware.contracts import Condition, JobStatus
from intentaware.delegation import LiveDelegator, MockRetriever, RetrievedDocument
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
