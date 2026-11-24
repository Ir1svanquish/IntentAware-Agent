"""Run the desktop's main workflows against a temporary database offscreen."""

import time
from threading import Event

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from intentaware.contracts import Condition, DelegationResult, JobStatus


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["intentaware-tests", "-platform", "offscreen"])


@pytest.fixture
def open_window(app, tmp_path):
    from intentaware.ui import MainWindow
    from intentaware.memory.store import SQLiteStore
    from intentaware.session import DesktopSession

    windows = []

    def open_session(**kwargs):
        session = DesktopSession(SQLiteStore(tmp_path / "ui.sqlite3"), **kwargs)
        window = MainWindow(session)
        windows.append(window)
        window.show()
        return window, session

    yield open_session
    for window in windows:
        window.close()


def test_goal_detour_and_resume_from_window(open_window):
    window, session = open_window()
    window.correction_button.click()
    window.goal_input.setText("完成研究报告")
    window.next_step_input.setText("整理方法章节")
    window.progress_input.setText("已收集三篇论文")
    window.save_goal_button.click()

    assert session.goal.title == "完成研究报告"
    assert session.progress.note == "已收集三篇论文"

    activity = "顺便看看新的演示文稿模板"
    window.manual_toggle.click()
    window.activity_input.setPlainText(activity)
    window.analyze_button.click()
    assert window.activity_input.isEnabled() is False
    wait_until(lambda: session.classification is not None)
    assert session.classification.reason in window.classification_label.text()
    window.detour_button.click()
    assert [detour.text for detour in session.detours] == [activity]
    assert activity in window.detour_list.item(0).text()

    window.resume_button.click()
    assert "整理方法章节" in window.resume_label.text()


def test_empty_goal_and_example_do_not_create_data(open_window):
    window, session = open_window()
    window.correction_button.click()
    window.goal_input.setText("  ")
    window.save_goal_button.click()
    assert session.goal is None
    assert window.status_label.text().strip()

    window.sample_button.click()
    assert window.goal_input.text().strip()
    assert window.activity_input.toPlainText().strip()
    assert session.goal is None


def test_detour_editor_crud_and_recovery_controls(open_window):
    window, session = open_window(condition=Condition.P)
    window.sample_button.click()
    window.save_goal_button.click()
    window.detours_nav.click()
    window.new_detour_button.click()
    window.detour_text_input.setPlainText("稍后核对参考文献")
    window.detour_url_input.setText("https://example.org/paper")
    window.detour_purpose_input.setText("写完方法后检查引用")
    window.save_detour_button.click()
    assert not window.detour_editor.isVisible()
    assert session.detours[0].purpose == "写完方法后检查引用"
    assert "https://example.org/paper" in window.detour_list.item(0).text()

    window.detour_list.setCurrentRow(0)
    window.edit_detour_button.click()
    window.detour_text_input.setPlainText("更新后的笔记")
    window.detour_url_input.setText("invalid-link")
    window.save_detour_button.click()
    assert window.detour_editor.isVisible()
    assert "链接" in window.detour_error.text()
    assert session.detours[0].text == "稍后核对参考文献"
    window.detour_url_input.setText("https://example.org/updated")
    window.save_detour_button.click()
    assert session.detours[0].text == "更新后的笔记"

    window.ignore_recovery_button.click()
    assert "已忽略" in window.resume_label.text()
    window.pause_recovery_button.click()
    assert session.recovery_paused
    assert "已暂停" in window.resume_label.text()
    window.resume_button.click()
    assert session.goal.next_step in window.resume_label.text()
    window.pause_recovery_button.click()
    assert not session.recovery_paused
    window.remove_detour_button.click()
    assert session.detours == []
    assert window.detour_empty.isVisible()


def test_memory_editor_preserves_draft_on_failed_storage_and_closes_on_task_switch(open_window, monkeypatch):
    import sqlite3

    window, session = open_window()
    window.sample_button.click()
    window.save_goal_button.click()
    window.detours_nav.click()
    window.new_detour_button.click()
    window.detour_text_input.setPlainText("尚未保存的笔记")

    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("数据库暂时不可用")
        patch.setattr(session.store, "append_event", fail)
        window.save_detour_button.click()
        assert window.detour_editor.isVisible()
        assert window.detour_text_input.toPlainText() == "尚未保存的笔记"
        assert "数据库暂时不可用" in window.detour_error.text()
        assert session.detours == []
    window.save_detour_button.click()
    assert len(session.detours) == 1
    window.detour_list.setCurrentRow(0)
    window.edit_detour_button.click()
    session.start_goal("另一个任务", "列提纲")
    window._refresh()
    assert not window.detour_editor.isVisible()
    assert window.detour_list.count() == 0
    assert "另一个任务" in window.resume_label.text()


def test_deferred_job_keeps_window_responsive_and_hides_answer(open_window):
    release = Event()
    answer = "测试答案：应在检查点交付。"

    class ControlledDelegator:
        def run(self, question, cancel):
            release.wait(3)
            return DelegationResult(answer)

    window, session = open_window(condition=Condition.D, delegator=ControlledDelegator())
    window.sample_button.click()
    window.save_goal_button.click()
    window.question_input.setText("何时交付？")
    window.submit_button.click()

    try:
        job = session.jobs[0]
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(job.status))
        QTest.qWait(30)
        assert ticks == [JobStatus.RUNNING]
        assert window.checkpoint_button.visibleRegion().boundingRect() == window.checkpoint_button.rect()
        assert answer not in window.job_result.toPlainText()

        window.condition_combo.setCurrentIndex(window.condition_combo.findData(Condition.I.value))
        assert session.condition == Condition.D
        assert window.condition_combo.currentData() == Condition.D.value

        release.set()
        wait_until(lambda: job.status != JobStatus.RUNNING)
        assert job.status == JobStatus.READY
        assert window.job_list.currentItem() is not None
        assert answer not in window.job_result.toPlainText()
        window.condition_combo.setCurrentIndex(window.condition_combo.findData(Condition.I.value))
        assert window.condition_combo.currentData() == Condition.D.value

        window.checkpoint_button.click()
        assert job.status == JobStatus.DELIVERED
        assert answer in window.job_result.toPlainText()

        window.condition_combo.setCurrentIndex(window.condition_combo.findData(Condition.P.value))
        assert session.condition == Condition.P
        assert not window.submit_button.isEnabled()
        assert window.delegation_unavailable.isVisible()
        assert not window.job_result.toPlainText()

        window.condition_combo.setCurrentIndex(window.condition_combo.findData(Condition.G.value))
        assert session.condition == Condition.G
        assert not window.detour_button.isEnabled()
        window.detours_nav.click()
        assert window.detour_unavailable.isVisible()
    finally:
        release.set()


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), "the Qt event loop did not receive the background result"
