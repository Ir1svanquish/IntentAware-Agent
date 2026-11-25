"""桌面会话使用的 SQLite 存储，在主线程创建和访问。"""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from intentaware.contracts import Condition, Detour, ExperimentEvent, Goal, Progress


_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    next_step TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_goal (
    slot INTEGER PRIMARY KEY CHECK (slot = 1),
    goal_id TEXT NOT NULL REFERENCES goals(id)
);
CREATE TABLE IF NOT EXISTS progress (
    goal_id TEXT PRIMARY KEY NOT NULL REFERENCES goals(id),
    note TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS detours (
    id TEXT PRIMARY KEY NOT NULL,
    goal_id TEXT NOT NULL REFERENCES goals(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY,
    id TEXT UNIQUE NOT NULL,
    run_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
"""


class SQLiteStore:
    def __init__(self, path: str | Path):
        self._database_path = None if str(path) == ":memory:" else Path(path).resolve()
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self._rollback_only = False
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.executescript(_SCHEMA)
            # Additive migration: keep existing tasks, timestamps and associations.
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                columns = {row["name"] for row in self._db.execute("PRAGMA table_info(detours)")}
                for name in ("url", "purpose"):
                    if name not in columns:
                        self._db.execute(f"ALTER TABLE detours ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        except sqlite3.Error:
            self._db.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """将一组写入作为一个事务提交，内部写入共享同一事务。"""
        outermost = self._transaction_depth == 0
        if outermost:
            self._db.execute("BEGIN")
            self._rollback_only = False

        self._transaction_depth += 1
        try:
            yield
            if outermost:
                if self._rollback_only:
                    raise RuntimeError("事务中的写入失败，所有变更已撤销。")
                self._db.commit()
        except BaseException:
            if outermost:
                self._db.rollback()
            else:
                self._rollback_only = True
            raise
        finally:
            self._transaction_depth -= 1

    def save_goal(self, goal: Goal) -> None:
        if not isinstance(goal.title, str) or not goal.title.strip():
            raise ValueError("任务目标不能为空。")
        with self.transaction():
            self._db.execute(
                """INSERT INTO goals (id, title, next_step, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET title = excluded.title,
                       next_step = excluded.next_step, created_at = excluded.created_at""",
                (goal.id, goal.title, goal.next_step, goal.created_at),
            )
            self._db.execute(
                """INSERT INTO active_goal (slot, goal_id) VALUES (1, ?)
                   ON CONFLICT (slot) DO UPDATE SET goal_id = excluded.goal_id""",
                (goal.id,),
            )

    def load_goal(self) -> Goal | None:
        row = self._db.execute(
            """SELECT goals.* FROM goals JOIN active_goal ON active_goal.goal_id = goals.id"""
        ).fetchone()
        return Goal(**row) if row is not None else None

    def save_progress(self, progress: Progress) -> None:
        with self.transaction():
            self._db.execute(
                """INSERT INTO progress (goal_id, note, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT (goal_id) DO UPDATE SET note = excluded.note,
                       updated_at = excluded.updated_at""",
                (progress.goal_id, progress.note, progress.updated_at),
            )

    def load_progress(self, goal_id: str) -> Progress | None:
        row = self._db.execute("SELECT * FROM progress WHERE goal_id = ?", (goal_id,)).fetchone()
        return Progress(**row) if row is not None else None

    def get_setting(self, key: str, default=None):
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row is not None else default

    def set_setting(self, key: str, value) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self.transaction():
            self._db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, payload),
            )

    def add_detour(self, detour: Detour) -> None:
        self._validate_detour(detour)
        with self.transaction():
            self._db.execute(
                "INSERT INTO detours (id, goal_id, text, created_at, url, purpose) VALUES (?, ?, ?, ?, ?, ?)",
                (detour.id, detour.goal_id, detour.text, detour.created_at, detour.url, detour.purpose),
            )

    @staticmethod
    def _validate_detour(detour: Detour) -> None:
        if not isinstance(detour.text, str) or not detour.text.strip():
            raise ValueError("支线笔记不能为空。")
        if not isinstance(detour.url, str) or not isinstance(detour.purpose, str):
            raise ValueError("链接和用途必须是文字。")
        if detour.url:
            try:
                parsed = urlsplit(detour.url)
                valid = parsed.scheme in ("http", "https") and bool(parsed.hostname)
                valid = valid and not any(character.isspace() for character in detour.url)
                parsed.port  # Validate malformed port numbers as well.
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("请输入完整的 http:// 或 https:// 链接，或将链接留空。")

    def update_detour(self, detour: Detour) -> None:
        """Update content only; never reassign a detour to another goal."""
        self._validate_detour(detour)
        with self.transaction():
            cursor = self._db.execute(
                "UPDATE detours SET text = ?, url = ?, purpose = ? WHERE id = ? AND goal_id = ?",
                (detour.text, detour.url, detour.purpose, detour.id, detour.goal_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("找不到当前任务的这条支线记录。")

    def list_detours(self, goal_id: str) -> list[Detour]:
        rows = self._db.execute("SELECT * FROM detours WHERE goal_id = ? ORDER BY rowid", (goal_id,))
        return [Detour(**row) for row in rows]

    def remove_detour(self, detour_id: str) -> None:
        with self.transaction():
            self._db.execute("DELETE FROM detours WHERE id = ?", (detour_id,))

    def append_event(self, event: ExperimentEvent) -> None:
        with self.transaction():
            payload = json.dumps(asdict(event), ensure_ascii=False)
            self._db.execute(
                "INSERT INTO events (id, run_id, payload) VALUES (?, ?, ?)",
                (event.id, event.run_id, payload),
            )

    def _event_rows(self, run_id: str | None) -> sqlite3.Cursor:
        return self._db.execute(
            "SELECT payload FROM events WHERE (? IS NULL OR run_id = ?) ORDER BY sequence",
            (run_id, run_id),
        )

    def list_events(self, run_id: str | None = None) -> list[ExperimentEvent]:
        events = []
        for row in self._event_rows(run_id):
            data = json.loads(row["payload"])
            data["condition"] = Condition(data["condition"])
            events.append(ExperimentEvent(**data))
        return events

    def export_events(self, path: str | Path, run_id: str | None = None) -> int:
        target = Path(path)
        if self._database_path is not None:
            try:
                same_file = target.samefile(self._database_path)
            except FileNotFoundError:
                same_file = False
            if same_file or target.resolve() == self._database_path:
                raise ValueError("请选择其他路径，以保留本地数据库。")

        temporary_file = NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=".intentaware-", suffix=".tmp", delete=False,
        )
        temporary_path = Path(temporary_file.name)
        count = 0
        try:
            with temporary_file:
                for row in self._event_rows(run_id):
                    temporary_file.write(row["payload"] + "\n")
                    count += 1
            os.replace(temporary_path, target)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        return count

    def close(self) -> None:
        self._db.close()
