"""Exercise the integration contract, persistence and delivery rules."""

import time
import sqlite3
from threading import Event

import pytest

from intentaware.contracts import ActivityLabel, Classification, Condition, DelegationResult, JobStatus
from intentaware.delegation.demo import DemoDelegator
from intentaware.memory.store import SQLiteStore
from intentaware.session import DesktopSession


def make_session(tmp_path, **kwargs):
    return DesktopSession(SQLiteStore(tmp_path / "data.sqlite3"), **kwargs)


def finish(session, job):
    deadline = time.monotonic() + 3
    while job.status == JobStatus.RUNNING and time.monotonic() < deadline:
        session.poll()
        time.sleep(0.005)
    assert job.status != JobStatus.RUNNING, "worker did not finish"


def test_goal_and_detour_survive_restart(tmp_path):
    session = make_session(tmp_path)
    try:
        goal = session.set_goal("完成论文", "整理三篇文献", "已经确定研究问题")
        session.add_detour("晚点看 O'Reilly 的教程")
        assert "整理三篇文献" in session.resume()
    finally:
        session.close()
    reopened = make_session(tmp_path)
    try:
        assert reopened.goal.id == goal.id
        assert reopened.progress.note == "已经确定研究问题"
        assert [d.text for d in reopened.detours] == ["晚点看 O'Reilly 的教程"]
    finally:
        reopened.close()


@pytest.mark.parametrize("condition, expected", [(Condition.I, JobStatus.DELIVERED), (Condition.D, JobStatus.READY)])
def test_completion_and_delivery_are_separate(tmp_path, condition, expected):
    session = make_session(tmp_path, condition=condition, delegator=DemoDelegator(delay_seconds=0.01))
    try:
        session.set_goal("完成论文", "写研究问题")
        job = session.submit_delegation("什么是任务恢复？")
        finish(session, job)
        assert job.status == expected
        assert job.completed_at
        if condition == Condition.D:
            assert job.delivered_at is None
            assert not any(e.name == "delegation_delivered" for e in session.events)
            assert session.checkpoint() == 1
        assert job.status == JobStatus.DELIVERED
        assert job.delivered_at
        names = [e.name for e in session.events]
        assert names.index("delegation_completed") < names.index("delegation_delivered")
        assert session.checkpoint() == 0
    finally:
        session.close()


class WaitingDelegator:
    def __init__(self):
        self.started = Event()
        self.release = Event()

    def run(self, question, cancel):
        self.started.set()
        self.release.wait(2)
        return DelegationResult("late answer")


def test_cancel_ignores_late_result(tmp_path):
    provider = WaitingDelegator()
    session = make_session(tmp_path, delegator=provider)
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("侧问题")
        assert provider.started.wait(1)
        session.cancel_job(job.id)
        provider.release.set()
        assert job.status == JobStatus.CANCELLED
        assert job.result is None
        with pytest.raises(ValueError):
            session.reveal_job(job.id)
    finally:
        provider.release.set()
        session.close()
    assert job.status == JobStatus.CANCELLED
    assert job.result is None


def test_empty_input_and_condition_gates(tmp_path):
    session = make_session(tmp_path, condition=Condition.G)
    try:
        with pytest.raises(ValueError):
            session.set_goal("  ", "")
        assert session.goal is None
        session.set_goal("目标", "下一步")
        with pytest.raises(ValueError):
            session.analyze("  ")
        with pytest.raises(ValueError):
            session.add_detour("支线")
        with pytest.raises(ValueError):
            session.submit_delegation("问题")
        session.set_condition(Condition.P)
        session.add_detour("支线")
        with pytest.raises(ValueError):
            session.submit_delegation("问题")
        session.set_condition(Condition.D)
        with pytest.raises(ValueError):
            session.submit_delegation(" ")
        assert session.jobs == []
    finally:
        session.close()


def test_condition_cannot_change_while_answer_waits(tmp_path):
    session = make_session(tmp_path, delegator=DemoDelegator(delay_seconds=0.01))
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("问题")
        with pytest.raises(ValueError):
            session.set_condition(Condition.I)
        finish(session, job)
        with pytest.raises(ValueError):
            session.set_condition(Condition.I)
        session.reveal_job(job.id)
        session.set_condition(Condition.I)
        assert session.condition == Condition.I
    finally:
        session.close()


def test_exported_events_can_be_joined_and_no_fake_edit(tmp_path):
    import json
    session = make_session(tmp_path)
    try:
        session.set_goal("私人目标文本", "下一步")
        session.resume()
        path = tmp_path / "events.jsonl"
        count = session.export_events(path)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == count
        assert all(row["run_id"] == session.run_id for row in rows)
        assert all(row["condition"] == "D" for row in rows)
        assert any(row["name"] == "resume_requested" for row in rows)
        assert not any(row["name"] == "meaningful_edit" for row in rows)
        assert "私人目标文本" not in path.read_text(encoding="utf-8")
    finally:
        session.close()


class BlockingClassifier:
    def __init__(self):
        self.started = Event()
        self.release = Event()

    def classify(self, context):
        self.started.set()
        self.release.wait(2)
        return Classification(ActivityLabel.NECESSARY_PREPARATION, "准备资料", context.goal.next_step)


def test_classification_runs_in_background_and_preserves_input_context(tmp_path):
    provider = BlockingClassifier()
    session = make_session(tmp_path, classifier=provider)
    try:
        session.set_goal("完成论文", "整理文献")
        session.start_analysis("阅读相关论文")
        assert provider.started.wait(1)
        assert session.analysis_pending
        assert session.classification is None
        provider.release.set()
        deadline = time.monotonic() + 3
        while session.analysis_pending and time.monotonic() < deadline:
            session.poll()
            time.sleep(0.005)
        assert not session.analysis_pending
        assert session.classification.label == ActivityLabel.NECESSARY_PREPARATION
        assert session.classification.suggested_next_step == "整理文献"
        assert session.analysis_error is None
        assert any(event.name == "activity_classified" for event in session.events)
    finally:
        provider.release.set()
        session.close()


def test_saving_goal_discards_a_classification_already_running(tmp_path):
    provider = BlockingClassifier()
    session = make_session(tmp_path, classifier=provider)
    try:
        session.set_goal("完成论文", "整理文献")
        session.start_analysis("阅读相关论文")
        assert provider.started.wait(1)
        old_analysis = session._analysis_future

        session.set_goal("完成报告", "核对数据", "完成图表")
        assert not session.analysis_pending
        assert session.store.load_goal().title == "完成报告"
        assert session.progress.note == "完成图表"

        provider.release.set()
        old_analysis.result(timeout=2)
        session.poll()
        assert session.classification is None
        assert all(event.name != "activity_classified" for event in session.events)
    finally:
        provider.release.set()
        session.close()


class FailingDelegator:
    def run(self, question, cancel):
        raise RuntimeError("演示错误：请求失败")


def test_worker_failure_is_a_failed_job_not_a_crash(tmp_path):
    session = make_session(tmp_path, delegator=FailingDelegator())
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("问题")
        finish(session, job)
        assert job.status == JobStatus.FAILED
        assert job.result is None
        assert "请求失败" in job.error
        assert any(event.name == "delegation_failed" for event in session.events)
        session.set_goal("仍然能编辑", "下一步")
    finally:
        session.close()


@pytest.mark.parametrize("condition", [Condition.G, Condition.I])
def test_new_condition_does_not_reuse_previous_run_answers(tmp_path, condition):
    session = make_session(tmp_path, delegator=DemoDelegator(delay_seconds=0))
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("旧轮次的问题")
        finish(session, job)
        session.reveal_job(job.id)
        old_run = session.run_id
        session.set_condition(condition)
        assert session.run_id != old_run
        assert session.jobs == []
        with pytest.raises(ValueError):
            session.reveal_job(job.id)
        assert any(e.name == "delegation_delivered" for e in session.store.list_events(old_run))
    finally:
        session.close()


def test_checkpoint_drains_already_finished_worker(tmp_path):
    session = make_session(tmp_path, delegator=DemoDelegator(delay_seconds=0))
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("问题")
        # Freeze the scenario between worker completion and the next Qt timer tick.
        session._pending[job.id][0].result(timeout=2)
        assert job.status == JobStatus.RUNNING
        assert session.checkpoint() == 1
        assert job.status == JobStatus.DELIVERED
        names = [e.name for e in session.events]
        assert names.index("delegation_completed") < names.index("delegation_delivered")
    finally:
        session.close()


def execute_sql(path, statement):
    with sqlite3.connect(path) as db:
        db.execute(statement)


def test_failed_save_rolls_back_goal_progress_and_event(tmp_path):
    session = make_session(tmp_path)
    db_path = tmp_path / "data.sqlite3"
    try:
        original = session.set_goal("原目标", "原步骤", "原进度")
        original_events = len(session.events)
        execute_sql(db_path, "CREATE TRIGGER fail_progress BEFORE INSERT ON progress BEGIN SELECT RAISE(ABORT, 'write failed'); END")
        with pytest.raises(sqlite3.IntegrityError):
            session.set_goal("新目标", "新步骤", "新进度")
        assert session.goal == original
        assert session.store.load_goal() == original
        assert session.store.load_progress(original.id).note == "原进度"
        assert len(session.events) == original_events
    finally:
        execute_sql(db_path, "DROP TRIGGER IF EXISTS fail_progress")
        session.close()


def test_completed_job_retries_after_event_write_recovers(tmp_path):
    session = make_session(tmp_path, condition=Condition.I, delegator=DemoDelegator(delay_seconds=0))
    db_path = tmp_path / "data.sqlite3"
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("问题")
        session._pending[job.id][0].result(timeout=2)
        execute_sql(db_path, "CREATE TRIGGER fail_events BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'write failed'); END")
        with pytest.raises(sqlite3.IntegrityError):
            session.poll()
        execute_sql(db_path, "DROP TRIGGER fail_events")
        assert session.poll()
        assert job.status == JobStatus.DELIVERED
        names = [e.name for e in session.events if e.job_id == job.id]
        assert names.count("delegation_completed") == 1
        assert names.count("delegation_delivered") == 1
    finally:
        execute_sql(db_path, "DROP TRIGGER IF EXISTS fail_events")
        session.close()


def test_malformed_source_is_reported_as_a_failed_job(tmp_path):
    class MalformedDelegator:
        def run(self, question, cancel):
            return DelegationResult("answer", sources=({"title": "wrong type", "url": "https://example.com"},))

    session = make_session(tmp_path, condition=Condition.I, delegator=MalformedDelegator())
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("问题")
        finish(session, job)
        assert job.status == JobStatus.FAILED
        assert job.result is None
    finally:
        session.close()


def test_cancel_ready_job_preserves_completion_time(tmp_path, monkeypatch):
    session = make_session(tmp_path, delegator=DemoDelegator(delay_seconds=0))
    try:
        session.set_goal("目标", "下一步")
        job = session.submit_delegation("问题")
        finish(session, job)
        completed_at = job.completed_at
        monkeypatch.setattr("intentaware.session.utc_now", lambda: "2099-01-01T00:00:00+00:00")
        session.cancel_job(job.id)
        assert job.status == JobStatus.CANCELLED
        assert job.completed_at == completed_at
    finally:
        session.close()
