"""Module C acceptance: migrations, editing, recovery and atomic failures."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from intentaware.contracts import Condition, Detour, Goal
from intentaware.memory.store import SQLiteStore
from intentaware.session import DesktopSession


def test_old_database_migrates_without_losing_records(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as database:
        database.executescript("""
            CREATE TABLE goals (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                next_step TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE active_goal (slot INTEGER PRIMARY KEY, goal_id TEXT NOT NULL);
            CREATE TABLE detours (id TEXT PRIMARY KEY, goal_id TEXT NOT NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO goals VALUES ('g', '写报告', '整理结果', '2026-11-23');
            INSERT INTO active_goal VALUES (1, 'g');
            INSERT INTO detours VALUES ('d', 'g', '稍后查资料', '2026-11-23');
        """)
    for _ in range(2):  # Migration must be safe on every subsequent launch.
        store = SQLiteStore(path)
        try:
            assert store.load_goal().title == "写报告"
            record = store.list_detours("g")[0]
            assert record.text == "稍后查资料"
            assert record.created_at == "2026-11-23"
            assert record.url == record.purpose == ""
        finally:
            store.close()
    store = SQLiteStore(path)
    try:
        updated = replace(store.list_detours("g")[0], text="升级后修改", url="https://example.org", purpose="检查兼容性")
        store.update_detour(updated)
    finally:
        store.close()
    reopened = SQLiteStore(path)
    try:
        assert reopened.list_detours("g") == [updated]
    finally:
        reopened.close()


def test_two_connections_can_migrate_the_same_old_database(tmp_path, monkeypatch):
    path = tmp_path / "concurrent-old.sqlite3"
    goal = Goal(title="旧任务", next_step="继续写报告")
    detour = Detour(goal_id=goal.id, text="旧支线")
    seed = SQLiteStore(path)
    try:
        seed.save_goal(goal)
        seed.add_detour(detour)
    finally:
        seed.close()

    connect = sqlite3.connect
    with connect(path) as database:
        database.execute("ALTER TABLE detours DROP COLUMN url")
        database.execute("ALTER TABLE detours DROP COLUMN purpose")

    # Hold a real writer lock until both independent connections reach their
    # first migration write. Without a transaction covering the schema read,
    # both have already read the old columns and one tries to add them twice.
    blocker = connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    waiting_for_lock = Barrier(3)

    def traced_connect(*args, **kwargs):
        database = connect(*args, **kwargs)
        reached_migration = False

        def trace(statement):
            nonlocal reached_migration
            if not reached_migration and (
                statement == "BEGIN IMMEDIATE"
                or statement.startswith("ALTER TABLE detours ADD COLUMN")
            ):
                reached_migration = True
                waiting_for_lock.wait(timeout=10)

        database.set_trace_callback(trace)
        return database

    monkeypatch.setattr(sqlite3, "connect", traced_connect)

    def open_old_database():
        store = SQLiteStore(path)
        try:
            columns = [row["name"] for row in store._db.execute("PRAGMA table_info(detours)")]
            return store.load_goal(), store.list_detours(goal.id), columns
        finally:
            store.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            opened = [workers.submit(open_old_database) for _ in range(2)]
            try:
                waiting_for_lock.wait(timeout=10)
            finally:
                blocker.rollback()
            results = [future.result(timeout=10) for future in opened]
    finally:
        blocker.close()

    for restored_goal, restored_detours, columns in results:
        assert restored_goal == goal
        assert restored_detours == [detour]
        assert columns.count("url") == columns.count("purpose") == 1


def test_full_detour_crud_survives_restart(tmp_path):
    path = tmp_path / "memory.sqlite3"
    session = DesktopSession(SQLiteStore(path), condition=Condition.P)
    try:
        goal = session.set_goal("完成报告", "整理结果", "已写方法")
        record = session.add_detour("O'Reilly 参考资料", "https://example.org/a?q='b'", "写完结果后查看")
        edited = session.update_detour(record.id, "新的笔记", "https://example.org/b", "核对参考文献")
        assert edited.id == record.id
        assert edited.created_at == record.created_at
        assert edited.goal_id == goal.id
        assert session.detours == [edited]
    finally:
        session.close()
    reopened = DesktopSession(SQLiteStore(path), condition=Condition.P)
    try:
        assert reopened.goal == goal
        assert reopened.progress.note == "已写方法"
        assert reopened.detours == [edited]
        reopened.remove_detour(edited.id)
    finally:
        reopened.close()
    store = SQLiteStore(path)
    try:
        assert store.list_detours(goal.id) == []
    finally:
        store.close()


def test_detours_cannot_be_edited_through_another_task(tmp_path):
    session = DesktopSession(SQLiteStore(tmp_path / "memory.sqlite3"))
    try:
        first = session.set_goal("写论文", "方法章节")
        record = session.add_detour("论文的参考资料")
        second = session.start_goal("做演示", "开场页")
        assert session.detours == []
        with pytest.raises(ValueError, match="找不到"):
            session.update_detour(record.id, "错误修改")
        with pytest.raises(ValueError, match="找不到"):
            session.remove_detour(record.id)
        with pytest.raises(ValueError, match="找不到"):
            session.store.update_detour(replace(record, goal_id=second.id))
        assert session.store.list_detours(first.id) == [record]
    finally:
        session.close()


@pytest.mark.parametrize("url", ["file:///tmp/a", "javascript:alert(1)", "https://", "https://a b", "https://a:bad"])
def test_invalid_links_do_not_write_records(tmp_path, url):
    session = DesktopSession(SQLiteStore(tmp_path / "memory.sqlite3"))
    try:
        session.set_goal("写报告", "整理结果")
        before = len(session.events)
        with pytest.raises(ValueError, match="链接"):
            session.add_detour("参考资料", url)
        assert session.detours == []
        assert len(session.events) == before
    finally:
        session.close()


def test_empty_and_missing_records_have_clear_errors(tmp_path):
    session = DesktopSession(SQLiteStore(tmp_path / "memory.sqlite3"))
    try:
        assert "先" in session.recovery_preview()
        with pytest.raises(ValueError):
            session.resume()
        session.set_goal("写报告", "")
        record = session.add_detour("稍后查看")
        with pytest.raises(ValueError, match="不能为空"):
            session.update_detour(record.id, " \n ")
        with pytest.raises(ValueError, match="找不到"):
            session.update_detour("missing", "内容")
        assert session.detours == [record]
        assert "填写一个具体的下一步" in session.resume()
    finally:
        session.close()


def test_recovery_preferences_persist_and_progress_changes_renew_suggestion(tmp_path):
    path = tmp_path / "memory.sqlite3"
    session = DesktopSession(SQLiteStore(path))
    try:
        session.set_goal("完成报告", "编写方法", "已完成提纲")
        assert "编写方法" in session.recovery_preview()
        session.ignore_recovery()
    finally:
        session.close()
    session = DesktopSession(SQLiteStore(path))
    try:
        assert "已忽略" in session.recovery_preview()
        session.set_goal("完成报告", "整理实验结果", "已完成方法")
        assert "已忽略" not in session.recovery_preview()
        assert "整理实验结果" in session.recovery_preview()
        assert "已完成方法" in session.recovery_preview()
        session.set_recovery_paused(True)
    finally:
        session.close()
    session = DesktopSession(SQLiteStore(path))
    try:
        assert session.recovery_paused
        assert "已暂停" in session.recovery_preview()
        assert "整理实验结果" in session.resume()  # Explicit requests still work.
        assert session.recovery_paused
        session.set_recovery_paused(False)
        assert "整理实验结果" in session.recovery_preview()
        assert not any(event.name == "meaningful_edit" for event in session.events)
    finally:
        session.close()


def test_failed_event_write_rolls_back_edited_detour_and_preferences(tmp_path, monkeypatch):
    session = DesktopSession(SQLiteStore(tmp_path / "memory.sqlite3"))
    try:
        session.set_goal("写报告", "写结果")
        record = session.add_detour("原始内容")
        before = session.events

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("模拟写入失败")

        monkeypatch.setattr(session.store, "append_event", fail)
        for action in (
            lambda: session.update_detour(record.id, "未提交的新内容"),
            lambda: session.remove_detour(record.id),
            lambda: session.set_recovery_paused(True),
            session.ignore_recovery,
        ):
            with pytest.raises(sqlite3.OperationalError, match="模拟写入失败"):
                action()
        assert session.detours == [record]
        assert not session.recovery_paused
        assert "已忽略" not in session.recovery_preview()
        assert session.events == before
        monkeypatch.undo()
    finally:
        session.close()


def test_condition_g_cannot_modify_memory_or_preferences(tmp_path):
    session = DesktopSession(SQLiteStore(tmp_path / "memory.sqlite3"))
    try:
        session.set_goal("写报告", "写结果")
        record = session.add_detour("保留内容")
        session.set_condition(Condition.G)
        for action in (
            lambda: session.add_detour("新内容"),
            lambda: session.update_detour(record.id, "新内容"),
            lambda: session.remove_detour(record.id),
            lambda: session.set_recovery_paused(True),
            session.ignore_recovery,
            session.resume,
        ):
            with pytest.raises(ValueError):
                action()
        assert "未启用" in session.recovery_preview()
        session.set_condition(Condition.P)
        assert session.detours == [record]
    finally:
        session.close()


@pytest.mark.parametrize("operation", ["add", "edit", "delete"])
def test_real_sqlite_lock_preserves_memory_and_allows_retry(tmp_path, operation):
    path = tmp_path / "locked.sqlite3"
    session = DesktopSession(SQLiteStore(path))
    blocker = sqlite3.connect(path)
    try:
        session.set_goal("数据库锁验收", "继续写报告", "已确认进度")
        original = session.add_detour("已保存的笔记", "https://example.org", "保留用途")
        before_events = session.events
        session.store._db.execute("PRAGMA busy_timeout = 20")
        blocker.execute("BEGIN IMMEDIATE")
        actions = {
            "add": lambda: session.add_detour("新笔记"),
            "edit": lambda: session.update_detour(original.id, "修改后的笔记"),
            "delete": lambda: session.remove_detour(original.id),
        }
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            actions[operation]()
        assert session.detours == [original]
        assert session.events == before_events
        assert session.progress.note == "已确认进度"
        blocker.rollback()
        actions[operation]()  # A failed transaction must not poison future saves.
        assert len(session.events) == len(before_events) + 1
        expected = {"add": 2, "edit": 1, "delete": 0}[operation]
        assert len(session.detours) == expected
        if operation == "edit":
            assert session.detours[0].text == "修改后的笔记"
    finally:
        blocker.rollback()
        blocker.close()
        session.close()


def test_real_event_constraint_rolls_back_goal_progress_and_recovery(tmp_path):
    path = tmp_path / "constraint.sqlite3"
    session = DesktopSession(SQLiteStore(path))
    database = sqlite3.connect(path)
    try:
        goal = session.set_goal("原目标", "原下一步", "原进度")
        session.ignore_recovery()
        events = session.events
        database.executescript("""
            CREATE TRIGGER reject_test_event BEFORE INSERT ON events BEGIN
                SELECT RAISE(ABORT, 'event rejected by test constraint');
            END;
        """)
        with pytest.raises(sqlite3.IntegrityError, match="event rejected"):
            session.set_goal("新目标", "新下一步", "新进度")
        with pytest.raises(sqlite3.IntegrityError, match="event rejected"):
            session.resume()
        assert session.goal == goal
        assert session.store.load_goal() == goal
        assert session.progress.note == session.store.load_progress(goal.id).note == "原进度"
        assert "已忽略" in session.recovery_preview()
        assert session.events == events
        database.execute("DROP TRIGGER reject_test_event")
        session.set_goal("新目标", "新下一步", "新进度")
        assert "新下一步" in session.recovery_preview()
        assert "新进度" in session.recovery_preview()
    finally:
        database.execute("DROP TRIGGER IF EXISTS reject_test_event")
        database.close()
        session.close()
