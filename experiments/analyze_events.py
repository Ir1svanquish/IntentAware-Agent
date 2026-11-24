"""从实验事件 JSONL 计算委托延迟与任务恢复时间。

只消费界面的真实事件记录，不读取窗口标题正文，也不推断用户是否完成工作。
恢复时间严格按 Proposal 要求：以 ``resume_requested`` 之后的下一个
``effective_edit``（下一次有意义的主任务编辑）为终点，缺这个事件就如实
报告"不可计算"，绝不用返回按钮、窗口切换或标题分类替代。

研究者需在受控研究中显式记录终点事件：
    session.record_event("effective_edit", {"source": "manual"})
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

RESUME_EVENT = "resume_requested"
EFFECTIVE_EDIT_EVENT = "effective_edit"
SUBMIT_EVENT = "delegation_submitted"
COMPLETE_EVENT = "delegation_completed"
DELIVER_EVENT = "delegation_delivered"


def load_events(path: str | Path) -> list[dict]:
    """读取 JSONL，跳过空行，坏行报错。"""
    rows: list[dict] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise ValueError(f"事件第 {number} 行不是合法 JSON。") from None
        if not isinstance(row, dict):
            raise ValueError(f"事件第 {number} 行不是 JSON 对象。")
        for key in ("run_id", "condition", "name", "occurred_at"):
            if key not in row:
                raise ValueError(f"事件第 {number} 行缺少字段 {key!r}。")
        if _parse_time(row["occurred_at"]) is None:
            raise ValueError(f"事件第 {number} 行的 occurred_at 无法解析。")
        rows.append(row)
    return rows


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)


def _seconds_between(start: str, end: str) -> float | None:
    first, second = _parse_time(start), _parse_time(end)
    if first is None or second is None:
        return None
    return (second - first).total_seconds()


def _describe(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def delegation_delays(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """按 job_id 计算后台处理时长与交付延迟。

    - processing: submitted -> completed，衡量后台 Agent 耗时。
    - delivery: completed -> delivered，I 条件应接近 0，D 条件等待检查点。
    """
    submitted: dict[str, str] = {}
    completed: dict[str, str] = {}
    delivered: dict[str, tuple[str, str]] = {}
    methods: dict[str, int] = defaultdict(int)

    for event in events:
        name = event["name"]
        job_id = event.get("job_id")
        if not job_id:
            continue
        if name == SUBMIT_EVENT:
            submitted.setdefault(job_id, event["occurred_at"])
        elif name == COMPLETE_EVENT:
            completed.setdefault(job_id, event["occurred_at"])
        elif name == DELIVER_EVENT:
            delivered.setdefault(job_id, (event["occurred_at"], str(event.get("details", {}).get("method", "unknown"))))
            methods[str(event.get("details", {}).get("method", "unknown"))] += 1

    processing: list[float] = []
    delivery: list[float] = []
    for job_id, start in submitted.items():
        if job_id in completed:
            value = _seconds_between(start, completed[job_id])
            if value is not None and value >= 0:
                processing.append(value)
        if job_id in delivered:
            finish_time = completed.get(job_id, start)
            value = _seconds_between(finish_time, delivered[job_id][0])
            if value is not None and value >= 0:
                delivery.append(value)

    return {
        "jobs_submitted": len(submitted),
        "jobs_completed": len(completed),
        "jobs_delivered": len(delivered),
        "processing_seconds": _describe(processing),
        "delivery_seconds": _describe(delivery),
        "delivery_methods": dict(methods),
        "missing_completion": sorted(set(submitted) - set(completed)),
        "missing_delivery": sorted(set(completed) - set(delivered)),
    }


def resume_times(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """计算 resume_requested 到下一次 effective_edit 的恢复时间。

    终点必须是显式的有效编辑事件；缺失时计入 unresolved，返回 None，
    不以任何其他事件替代，避免把误提醒率或恢复时间算成假数据。
    """
    indexed = list(enumerate(events))
    measured: list[float] = []
    unresolved: list[dict[str, str]] = []

    for position, event in indexed:
        if event["name"] != RESUME_EVENT:
            continue
        run_id = event["run_id"]
        end = next(
            (
                later for _, later in indexed[position + 1:]
                if later["name"] == EFFECTIVE_EDIT_EVENT and later["run_id"] == run_id
            ),
            None,
        )
        if end is None:
            unresolved.append({"run_id": run_id, "occurred_at": event["occurred_at"]})
            continue
        value = _seconds_between(event["occurred_at"], end["occurred_at"])
        if value is None or value < 0:
            unresolved.append({"run_id": run_id, "occurred_at": event["occurred_at"]})
        else:
            measured.append(value)

    return {
        "resume_requests": sum(1 for e in events if e["name"] == RESUME_EVENT),
        "measured": _describe(measured),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
        "endpoint_definition": (
            "resume_requested 之后同一 run_id 的下一条 effective_edit；"
            "未显式记录则不计算，不以窗口切换或分类事件替代。"
        ),
    }


def condition_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """统计各实验条件的事件数。"""
    counter: dict[str, int] = defaultdict(int)
    for event in events:
        counter[str(event.get("condition", "unknown"))] += 1
    return dict(counter)


def summarize_events(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """汇总一份事件导出的 E 模块指标。"""
    run_ids = sorted({str(e["run_id"]) for e in events})
    return {
        "total_events": len(events),
        "run_ids": run_ids,
        "condition_counts": condition_counts(events),
        "delegation": delegation_delays(events),
        "resume": resume_times(events),
    }


__all__ = [
    "load_events", "delegation_delays", "resume_times", "condition_counts",
    "summarize_events", "RESUME_EVENT", "EFFECTIVE_EDIT_EVENT",
]
