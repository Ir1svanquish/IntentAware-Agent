"""Verify module C across interpreter exits, independently of Qt availability."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


def run_session(path, program, condition="P"):
    source = Path(__file__).resolve().parents[1] / "src"
    # Windows redirected stdout may use a legacy code page. Keep both ends
    # of the pipe in UTF-8 so Chinese task data survives the JSON round trip.
    environment = {
        **os.environ,
        "PYTHONPATH": str(source),
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(program), str(path), condition],
        env=environment, capture_output=True, text=True, encoding="utf-8",
        check=False, timeout=15,
    )
    assert result.returncode == 0, (
        f"Session subprocess exited with {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("stdio_encoding", ["utf-8", "cp1252"])
def test_recovery_state_survives_separate_processes(tmp_path, monkeypatch, paused, stdio_encoding):
    monkeypatch.setenv("PYTHONIOENCODING", stdio_encoding)
    path = tmp_path / "restart.sqlite3"
    written = run_session(path, f"""
        import json, sys
        from intentaware.memory.store import SQLiteStore
        from intentaware.session import DesktopSession
        session = DesktopSession(SQLiteStore(sys.argv[1]))
        try:
            goal = session.set_goal('进程重启验收任务', '检查参考文献', '已完成方法')
            record = session.add_detour('稍后检查引用', 'https://example.org/reference', '核对来源')
            record = session.update_detour(record.id, '已编辑的支线', record.url, record.purpose)
            session.ignore_recovery()
            session.set_recovery_paused({paused!r})
            print(json.dumps({{'goal_id': goal.id, 'detour_id': record.id}}))
        finally:
            session.close()
    """)
    restored = run_session(path, """
        import json, sys
        from intentaware.memory.store import SQLiteStore
        from intentaware.session import DesktopSession
        session = DesktopSession(SQLiteStore(sys.argv[1]))
        try:
            record = session.detours[0]
            preview = session.recovery_preview()
            result = dict(goal_id=session.goal.id, detour_id=record.id,
                title=session.goal.title, next_step=session.goal.next_step,
                progress=session.progress.note, text=record.text,
                url=record.url, purpose=record.purpose,
                paused=session.recovery_paused, preview=preview)
            session.set_recovery_paused(False)
            result['unpaused_preview'] = session.recovery_preview()
            result['manual_resume'] = session.resume()
            session.set_goal(session.goal.title, '检查最终稿', '已完成参考文献')
            print(json.dumps(result, ensure_ascii=False))
        finally:
            session.close()
    """)
    assert restored["goal_id"] == written["goal_id"]
    assert restored["detour_id"] == written["detour_id"]
    assert restored["title"] == "进程重启验收任务"
    assert restored["next_step"] == "检查参考文献"
    assert restored["progress"] == "已完成方法"
    assert restored["text"] == "已编辑的支线"
    assert restored["url"] == "https://example.org/reference"
    assert restored["purpose"] == "核对来源"
    assert restored["paused"] is paused
    assert ("已暂停" if paused else "已忽略") in restored["preview"]
    assert "已忽略" in restored["unpaused_preview"]
    assert "检查参考文献" in restored["manual_resume"]

    # A third fresh process checks both the revised task and condition gates.
    for condition in ("G", "P", "I", "D"):
        state = run_session(path, """
            import json, sys
            from intentaware.contracts import Condition
            from intentaware.memory.store import SQLiteStore
            from intentaware.session import DesktopSession
            session = DesktopSession(SQLiteStore(sys.argv[1]), condition=Condition(sys.argv[2]))
            try:
                result = dict(paused=session.recovery_paused,
                    memory_enabled=session.memory_enabled,
                    delegation_enabled=session.delegation_enabled,
                    next_step=session.goal.next_step, progress=session.progress.note,
                    preview=session.recovery_preview(), detour_count=len(session.detours))
                try:
                    result['resume'] = session.resume()
                except ValueError:
                    result['resume'] = 'disabled'
                print(json.dumps(result, ensure_ascii=False))
            finally:
                session.close()
        """, condition)
        assert state["paused"] is False
        assert state["next_step"] == "检查最终稿"
        assert state["progress"] == "已完成参考文献"
        assert state["detour_count"] == 1
        assert state["memory_enabled"] is (condition != "G")
        assert state["delegation_enabled"] is (condition in ("I", "D"))
        if condition == "G":
            assert state["resume"] == "disabled"
            assert "未启用" in state["preview"]
        else:
            assert "检查最终稿" in state["resume"]
            assert "已完成参考文献" in state["preview"]
