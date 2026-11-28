"""Automatic desktop interactions with the real monitor and a controlled OS boundary."""

import time

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from experiments.analyze_events import load_events, resume_times
from experiments.check_events import check_events
from intentaware.activity.demo import DemoObserver
from intentaware.activity.models import ActivitySnapshot, CaptureResult
from intentaware.activity.monitor import TaskMonitor
from intentaware.activity.observer import UnavailableObserver
from intentaware.contracts import ActivityLabel, JobStatus
from intentaware.delegation.demo import DEMO_QUESTION, DemoDelegator
from intentaware.localization import get_language, set_language
from intentaware.memory.store import SQLiteStore
from intentaware.nlp.local import LocalActivityClassifier
from intentaware.session import DesktopSession
from intentaware.ui import MainWindow


class WindowObserver:
    def __init__(self):
        self.result = CaptureResult(ActivitySnapshot("Microsoft Word", "研究报告.docx - Microsoft Word"))

    def capture(self):
        return self.result

    def observe(self, app_name, title):
        self.result = CaptureResult(ActivitySnapshot(app_name, title))


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), "automatic state did not reach the Qt workbench"


def observe(window, monitor, title, app_name="Microsoft Word"):
    monitor.observer.observe(app_name, title)
    wait_until(lambda: monitor.snapshot is not None and monitor.snapshot.window_title == title
               and bool(monitor.activity_text) and not window.session.analysis_pending)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["automatic-ui", "-platform", "offscreen"])


@pytest.fixture
def automatic_window(app, tmp_path):
    session = DesktopSession(SQLiteStore(tmp_path / "automatic-ui.sqlite3"), classifier=LocalActivityClassifier())
    monitor = TaskMonitor(session, WindowObserver(), stable_seconds=0, interval_seconds=0.02)
    window = MainWindow(session, monitor=monitor)
    window.show()
    wait_until(lambda: session.goal is not None and session.classification is not None and not session.analysis_pending)
    yield window, session, monitor
    window.close()


def test_unavailable_foreground_capture_guides_first_time_users_to_manual_setup(app, tmp_path):
    session = DesktopSession(SQLiteStore(tmp_path / "unavailable.sqlite3"))
    monitor = TaskMonitor(session, UnavailableObserver("当前环境无法提供窗口标题"))
    window = MainWindow(session, monitor=monitor)
    window.show()
    try:
        wait_until(lambda: monitor.state == "unavailable")
        assert session.goal is None
        assert "修正" in window.task_next_step.text()
        assert "自动出现" not in window.task_next_step.text()
        assert window.correction_button.isEnabled()
    finally:
        window.close()


def test_observations_update_without_editing_or_analyze_click(automatic_window):
    window, session, monitor = automatic_window
    assert window.task_title.text() == "撰写「研究报告」"
    assert not window.correction_editor.isVisible()
    assert not window.manual_panel.isVisible()

    observe(window, monitor, "访谈记录.docx - Microsoft Word")

    assert "访谈记录.docx" in window.window_title_label.text()
    assert "Microsoft Word" in window.activity_source.text()
    assert session.goal.title == "撰写「研究报告」"


@pytest.fixture
def interface_language(request):
    previous = get_language()
    set_language(request.param)
    yield request.param
    set_language(previous)


@pytest.mark.parametrize("interface_language", ["zh", "en"], indirect=True)
def test_mvp_demo_from_task_inference_to_checkpoint_and_export(app, tmp_path, monkeypatch, interface_language):
    english = interface_language == "en"
    progress = "Argument parsing is implemented" if english else "已实现参数解析"
    question = "How do I make an argparse option required?" if english else DEMO_QUESTION
    data_path = tmp_path / "demo.sqlite3"
    export_path = tmp_path / "events-demo.jsonl"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(export_path), "JSONL"))
    session = DesktopSession(
        SQLiteStore(data_path), delegator=DemoDelegator(delay_seconds=0, reference_sample=True),
        demo_mode=True,
    )
    monitor = TaskMonitor(session, DemoObserver(), stable_seconds=0)
    window = MainWindow(session, monitor=monitor, demo=True)
    window.show()
    try:
        wait_until(lambda: session.goal is not None and session.classification is not None)
        assert "IntentAware-Agent" in session.goal.title
        if english:
            assert window.page_title.text() == "Workbench"
            assert session.goal.title.startswith("Continue developing")
            assert monitor.activity_text.startswith("Foreground window:")
            window.correction_button.click()
            window.goal_input.clear()
            window.save_goal_button.click()
            assert window.status_label.text() == "Enter a goal for this task."
        goal_id = session.goal.id

        window.experiment_nav.click()
        window.sample_button.click()
        window.save_goal_button.click()
        assert session.goal.id == goal_id
        assert session.progress.note == progress
        wait_until(lambda: not session.analysis_pending)
        window.analyze_button.click()
        window.experiment_nav.click()
        wait_until(lambda: session.classification is not None
                   and session.classification.label == ActivityLabel.OPTIONAL_EXPLORATION)
        assert not any(e.name == "distraction_prompted" for e in session.events)
        window.workbench_nav.click()
        wait_until(lambda: any(e.name == "distraction_prompted" for e in session.events))
        if english:
            assert window.classification_title.text() == "Possible detour"
            assert session.classification.reason.startswith("Local rules: Detected")
            assert "Save the detour" in window.manual_classification_label.text()
        manual_activity = window.activity_input.toPlainText()
        assert window.detour_button.isEnabled()
        window.detour_button.click()
        assert [detour.text for detour in session.detours] == [manual_activity]
        assert window.detour_list.currentItem() is not None

        window.delegation_nav.click()
        assert window.question_input.text() == question
        window.formulate_button.click()
        assert not session.jobs
        window.confirm_draft_button.click()
        wait_until(lambda: bool(session.jobs) and session.jobs[0].status == JobStatus.READY)
        assert "required=" not in window.job_result.toPlainText()
        if english:
            assert window.job_list.item(0).text().startswith("Ready to deliver")

        window.detours_nav.click()
        window.resume_button.click()
        assert session.goal.next_step in window.resume_label.text()
        if english:
            assert "Confirmed progress:" in window.resume_label.text()
        assert not any(e.name == "effective_edit" for e in session.events)
        window.experiment_nav.click()
        window.effective_edit_button.click()

        window.delegation_nav.click()
        window.checkpoint_button.click()
        assert session.jobs[0].status == JobStatus.DELIVERED
        assert "required=" in window.job_result.toPlainText()
        assert "docs.python.org" in window.job_result.toPlainText()
        if english:
            assert "Verified excerpts" in window.job_result.toPlainText()
        window.experiment_nav.click()
        window.export_button.click()
        rows = load_events(export_path)
        assert rows[0]["details"]["observation_mode"] == "demo"
        assert [row["goal_id"] for row in rows
                if row["name"] in ("distraction_prompted", "effective_edit")] == [goal_id, goal_id]
        assert check_events(export_path).error_count == 0
        assert check_events(export_path).warning_count == 0
        assert resume_times(rows)["measured"]["n"] == 1
        assert question not in export_path.read_text(encoding="utf-8")
    finally:
        window.close()

    restored = DesktopSession(SQLiteStore(data_path))
    try:
        assert restored.goal.id == goal_id
        assert restored.progress.note == progress
        assert len(restored.detours) == 1
    finally:
        restored.close()


@pytest.mark.parametrize("interface_language", ["en"], indirect=True)
def test_settings_save_language_for_the_next_launch(app, tmp_path, monkeypatch, interface_language):
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("intentaware.ui.window.QSettings", lambda: settings)

    session = DesktopSession(SQLiteStore(tmp_path / "settings.sqlite3"))
    window = MainWindow(session)
    try:
        window.settings_nav.click()
        assert window.page_title.text() == "Settings"
        index = window.language_combo.findData("zh")
        window.language_combo.setCurrentIndex(index)
        window.language_combo.activated.emit(index)
        assert settings.value("language") == "zh"
        assert window.language_status.text() == "Language preference saved. Restart the app to apply it."
        assert window.page_title.text() == "Settings"
    finally:
        window.close()


def test_english_recognition_respects_an_existing_task(app, tmp_path):
    data_path = tmp_path / "previous.sqlite3"
    session = DesktopSession(SQLiteStore(data_path))
    goal = session.start_goal("继续开发「IntentAware-Agent」", "检查界面")
    session.close()

    previous = get_language()
    set_language("en")
    session = DesktopSession(SQLiteStore(data_path))
    monitor = TaskMonitor(session, DemoObserver(), stable_seconds=0)
    window = MainWindow(session, monitor=monitor, demo=True)
    window.show()
    try:
        wait_until(lambda: bool(monitor.activity_text))
        assert session.goal == goal
        assert window.task_title.text() == goal.title
        assert monitor.switch_suggestion is None
    finally:
        window.close()
        set_language(previous)


def test_polling_preserves_an_open_correction_draft(automatic_window):
    window, session, monitor = automatic_window
    window.correction_button.click()
    window.goal_input.setText("我正在写最终结论")
    window.next_step_input.setText("核对访谈结论")
    observe(window, monitor, "新的窗口标题.docx - Microsoft Word")

    assert window.goal_input.text() == "我正在写最终结论"
    window.save_goal_button.click()

    assert session.goal.title == "我正在写最终结论"
    assert session.goal.next_step == "核对访谈结论"
    assert window.task_title.text() == "我正在写最终结论"
    assert monitor.goal_origin == "manual"
    assert not window.correction_editor.isVisible()


def test_pause_hides_stale_activity_and_classification(automatic_window):
    window, session, monitor = automatic_window
    reason = session.classification.reason
    assert reason in window.classification_label.text()

    window.pause_button.click()

    assert monitor.state == "paused"
    assert "恢复" in window.pause_button.text()
    assert "暂停" in window.activity_label.text()
    assert reason not in window.classification_label.text()
    assert window.task_title.text() == "撰写「研究报告」"
    window.pause_button.click()
    wait_until(lambda: monitor.snapshot is not None)


def test_task_switch_requires_the_visible_adoption_action(automatic_window):
    window, session, monitor = automatic_window
    original_id = session.goal.id
    observe(window, monitor, "login.py - AccountPortal - Visual Studio Code", app_name="Code.exe")
    assert window.suggestion_card.isVisible()
    assert session.goal.title == "撰写「研究报告」"

    window.adopt_suggestion_button.click()

    assert session.goal.title == "继续开发「AccountPortal」"
    assert session.goal.id != original_id
    assert not window.suggestion_card.isVisible()


def test_corrected_task_does_not_offer_its_original_title_as_a_switch(automatic_window):
    window, session, monitor = automatic_window
    previous = session.goal.id
    window.correction_button.click()
    window.goal_input.setText("完成研究报告的方法章节")
    window.save_goal_button.click()

    assert session.goal.id == previous
    assert not window.suggestion_card.isVisible()
    observe(window, monitor, "访谈记录.docx - Microsoft Word")
    assert window.suggestion_card.isVisible()
    observe(window, monitor, "研究报告.docx - Microsoft Word")
    assert not window.suggestion_card.isVisible()


def test_cancel_correction_restores_the_suggestion_actions(automatic_window):
    window, _, monitor = automatic_window
    window.correction_button.click()
    observe(window, monitor, "访谈记录.docx - Microsoft Word")
    assert not window.suggestion_card.isVisible()

    window.cancel_correction_button.click()

    assert window.suggestion_card.isVisible()
    assert window.adopt_suggestion_button.isEnabled()


def test_dismissed_suggestion_stays_hidden_for_other_files_in_the_same_project(automatic_window):
    window, session, monitor = automatic_window
    original = session.goal
    observe(window, monitor, "login.py - AccountPortal - Visual Studio Code", app_name="Code.exe")
    assert window.suggestion_card.isVisible()
    window.dismiss_suggestion_button.click()

    assert session.goal == original
    assert not window.suggestion_card.isVisible()
    observe(window, monitor, "tests.py - AccountPortal - Visual Studio Code", app_name="Code.exe")
    assert not window.suggestion_card.isVisible()
    observe(window, monitor, "readme.py - NewProject - Visual Studio Code", app_name="Code.exe")
    assert window.suggestion_card.isVisible()


def test_excluding_current_app_updates_settings_and_clears_activity(automatic_window):
    window, session, monitor = automatic_window
    window.settings_nav.click()
    window.exclude_current_button.click()

    assert monitor.excluded_apps == ["microsoft word"]
    assert "microsoft word" in window.excluded_apps_input.toPlainText()
    assert "排除" in window.monitor_status.text()
    assert session.goal.title == "撰写「研究报告」"
    assert monitor.snapshot is None


def test_manual_analysis_stays_usable_while_automatic_capture_is_paused(automatic_window):
    window, session, monitor = automatic_window
    window.pause_button.click()
    window.manual_toggle.click()
    window.activity_input.setPlainText("顺便浏览了一些演示文稿模板")
    window.analyze_button.click()
    wait_until(lambda: session.classification is not None and not session.analysis_pending)

    assert "手动补充" in window.classification_label.text()
    assert session.classification.reason in window.classification_label.text()
    assert monitor.state == "paused"


def test_low_signal_window_does_not_offer_an_empty_task_switch(automatic_window):
    window, session, monitor = automatic_window
    observe(window, monitor, "新标签页 - Google Chrome", app_name="chrome.exe")

    assert not window.suggestion_card.isVisible()
    assert session.goal.title == "撰写「研究报告」"
    assert "需要确认" in window.confidence_label.text()


def test_closing_window_stops_observation_application(automatic_window):
    window, _, monitor = automatic_window
    previous = monitor.snapshot
    window.close()
    monitor.observer.observe("Code.exe", "other.py - OtherProject - Visual Studio Code")
    for _ in range(3):
        assert monitor.poll() is False
        QTest.qWait(40)
    assert monitor.snapshot == previous
