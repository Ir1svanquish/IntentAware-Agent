"""从实验事件 JSONL 计算委托延迟与任务恢复时间。

只消费界面的真实事件记录，不读取窗口标题正文，也不推断用户是否完成工作。

恢复时间严格按 Proposal 要求：从**支线提示出现**（``distraction_prompted``）
开始，到**下一次有意义的主任务编辑**（``effective_edit``）结束，两者必须在
同一 run、同一 goal_id 下。缺起点或终点就如实标注，绝不用"点击恢复主任务"
按钮、窗口切换或标题分类替代——点击恢复只是用户动作，不是分心开始时刻。

研究者需在受控研究中显式记录这两个事件：
    session.record_event("distraction_prompted", {"source": "optional_exploration"})
    session.record_event("effective_edit", {"source": "goal_correction"})
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

# 恢复时间起点只认实际的支线提示事件（Proposal 定义的分心开始时刻）。
# 注意：detour_saved 是"用户手动保存支线"，不是提示出现；若也当起点，
# 同一次分心会出现提示+保存两条起点、被算成两笔，故明确排除。
DISTRACTION_PROMPT_EVENT = "distraction_prompted"
START_EVENTS = (DISTRACTION_PROMPT_EVENT,)
RESUME_EVENT = "resume_requested"  # 仅作参考计数，不用于计时
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
    # 缺少完成时间的委托仍保留在 missing_completion 中，但不得进入
    # delivery_seconds：交付延迟的定义是 completed -> delivered，
    # 用 submitted 代替 completed 会把后台处理时间误算进交付延迟。
    excluded_from_delivery: list[str] = []
    for job_id, start in submitted.items():
        if job_id in completed:
            value = _seconds_between(start, completed[job_id])
            if value is not None and value >= 0:
                processing.append(value)
        if job_id in delivered:
            if job_id not in completed:
                excluded_from_delivery.append(job_id)
                continue
            value = _seconds_between(completed[job_id], delivered[job_id][0])
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
        "excluded_from_delivery": sorted(excluded_from_delivery),
        "delivery_definition": "completed -> delivered；缺完成时间的委托不计入。",
    }


def resume_times(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """计算支线提示出现到下一次有效主任务编辑的恢复时间。

    起点：仅 ``distraction_prompted``——分心/支线提示出现的时刻。
    ``detour_saved``（用户手动保存支线）不作为起点：它不是提示，且同一次
    分心可能既有提示又有手动保存，算两个起点会重复计时。
    终点：``effective_edit``——下一次有意义的主任务编辑。
    两者必须同一 run_id 且同一 goal_id；跨任务的下一次编辑不算恢复。

    ``resume_requested``（点击"恢复主任务"按钮）只作参考计数，不作为起点：
    用户可能在提示出现很久后才点击恢复，用它计时会漏掉中间的分心时长。
    缺起点或缺终点都明确列在 missing_start / missing_end 中，返回 None，
    不以按钮点击、窗口切换或标题分类替代。
    """
    indexed = list(enumerate(events))
    measured: list[float] = []
    missing_start: list[dict[str, str]] = []
    missing_end: list[dict[str, str]] = []

    # 每个起点配对同一 run、同一 goal 的下一条有效编辑。
    for position, event in indexed:
        if event["name"] not in START_EVENTS:
            continue
        run_id = event["run_id"]
        goal_id = event.get("goal_id")
        end = next(
            (
                later for _, later in indexed[position + 1:]
                if later["name"] == EFFECTIVE_EDIT_EVENT
                and later["run_id"] == run_id
                and later.get("goal_id") == goal_id
            ),
            None,
        )
        if end is None:
            missing_end.append({
                "run_id": run_id, "goal_id": str(goal_id or ""),
                "started_at": event["occurred_at"], "start_event": event["name"],
            })
            continue
        value = _seconds_between(event["occurred_at"], end["occurred_at"])
        if value is None or value < 0:
            missing_end.append({
                "run_id": run_id, "goal_id": str(goal_id or ""),
                "started_at": event["occurred_at"], "start_event": event["name"],
            })
        else:
            measured.append(value)

    # 有有效编辑但找不到同 run、同 goal 的起点：明确标注，不臆造起点。
    starts_by_key = {
        (e["run_id"], e.get("goal_id")) for e in events if e["name"] in START_EVENTS
    }
    for event in events:
        if event["name"] != EFFECTIVE_EDIT_EVENT:
            continue
        key = (event["run_id"], event.get("goal_id"))
        if key not in starts_by_key:
            missing_start.append({
                "run_id": event["run_id"], "goal_id": str(event.get("goal_id") or ""),
                "edited_at": event["occurred_at"],
            })

    return {
        "prompt_count": sum(1 for e in events if e["name"] in START_EVENTS),
        "resume_click_count": sum(1 for e in events if e["name"] == RESUME_EVENT),
        "measured": _describe(measured),
        "missing_start_count": len(missing_start),
        "missing_start": missing_start,
        "missing_end_count": len(missing_end),
        "missing_end": missing_end,
        "start_definition": (
            "起点仅为 distraction_prompted（支线提示出现）；detour_saved 是手动保存支线，"
            "不作为起点以免同一次分心重复计时；resume_requested 仅计为点击次数。"
        ),
        "endpoint_definition": (
            "终点为同一 run_id、同一 goal_id 的下一条 effective_edit；"
            "跨任务编辑、按钮点击、窗口切换与标题分类均不算终点。"
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
    "summarize_events", "DISTRACTION_PROMPT_EVENT",
    "START_EVENTS", "RESUME_EVENT", "EFFECTIVE_EDIT_EVENT",
]
