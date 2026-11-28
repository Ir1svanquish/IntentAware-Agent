"""Deterministic recovery from user-confirmed state; no API or inferred progress."""

import hashlib
import json

from intentaware.localization import tr
from intentaware.contracts import Detour, Goal, Progress


def recovery_key(goal: Goal, progress: Progress | None) -> str:
    """Ignore only this version of a suggestion; updated task state renews it."""
    state = [goal.id, goal.title, goal.next_step, progress.note if progress else ""]
    return hashlib.sha256(json.dumps(state, ensure_ascii=False).encode("utf-8")).hexdigest()


def recovery_text(goal: Goal, progress: Progress | None, detours: list[Detour]) -> str:
    lines = [tr("继续任务：{0}", goal.title)]
    if progress and progress.note.strip():
        lines.append(tr("已确认进度：{0}", progress.note))
    else:
        lines.append(tr("已确认进度：尚未记录；可在“修正”中补充。"))
    next_step = goal.next_step.strip() or tr("请先在“修正”中填写一个具体的下一步操作。")
    lines.append(tr("下一步：{0}", next_step))
    if detours:
        lines.append(tr("已暂存 {0} 条支线，先完成下一步，再按需查看。", len(detours)))
    return "\n".join(lines)
