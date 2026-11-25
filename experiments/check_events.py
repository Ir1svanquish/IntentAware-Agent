"""检查实验事件 JSONL 导出的完整性与结构一致性。

用途：研究分析之前先做一次机械校验，确认导出的事件记录没有缺字段、
时间倒序、委托生命周期不配对等低级问题。此工具只检查结构，不计算
Macro-F1、误提醒率等需要人工标注的指标，也不解读事件内容。

用法（在仓库根目录）：
    python -m experiments.check_events path/to/events.jsonl
    python -m experiments.check_events path/to/events.jsonl --json

退出码：0 表示没有发现问题；1 表示发现问题；2 表示文件无法读取。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ("id", "run_id", "condition", "name", "occurred_at")
VALID_CONDITIONS = frozenset({"G", "P", "I", "D"})
VALID_LABELS = frozenset({
    "direct_progress", "necessary_preparation",
    "optional_exploration", "unclear",
})
VALID_DELIVERY_METHODS = frozenset({"immediate", "checkpoint", "early_view"})

DELEGATION_LIFECYCLE = (
    "delegation_submitted", "delegation_completed",
    "delegation_delivered", "delegation_cancelled", "delegation_failed",
)
TERMINAL_JOB_EVENTS = ("delegation_delivered", "delegation_cancelled", "delegation_failed")


@dataclass
class Issue:
    """一条校验发现：带行号的结构错误或流程异常。"""

    line: int
    level: str  # "error" 或 "warning"
    code: str
    message: str

    def render(self) -> str:
        return f"第 {self.line} 行 [{self.level}/{self.code}] {self.message}"


@dataclass
class JobTrace:
    """单个委托在事件日志中的生命周期。"""

    submitted: int = 0
    completed: int = 0
    delivered: int = 0
    cancelled: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class RunSummary:
    """单个 run_id 的统计摘要。"""

    condition: str
    events: int
    first_event: str
    last_event: str
    event_counts: dict[str, int]
    labels: dict[str, int]
    jobs: dict[str, JobTrace]
    delivery_methods: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "events": self.events,
            "first_event": self.first_event,
            "last_event": self.last_event,
            "event_counts": self.event_counts,
            "labels": self.labels,
            "jobs": {job_id: trace.as_dict() for job_id, trace in self.jobs.items()},
            "delivery_methods": self.delivery_methods,
        }


@dataclass
class Report:
    """整份导出的校验结果。"""

    path: str
    total_events: int
    runs: dict[str, RunSummary] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "warning")

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "total_events": self.total_events,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "runs": {run_id: run.as_dict() for run_id, run in self.runs.items()},
            "issues": [asdict(issue) for issue in self.issues],
        }


def _parse_timestamp(value: object) -> datetime | None:
    """解析 ISO 8601 时间戳；失败返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _validate_row(row: dict[str, Any], line: int, issues: list[Issue]) -> bool:
    """检查单行必需字段；返回该行是否可用于统计。"""
    missing = [name for name in REQUIRED_FIELDS if name not in row]
    if missing:
        issues.append(Issue(
            line, "error", "missing_field",
            f"缺少必需字段：{', '.join(missing)}。",
        ))
        return False

    if row["condition"] not in VALID_CONDITIONS:
        issues.append(Issue(
            line, "error", "invalid_condition",
            f"condition 应为 G/P/I/D 之一，实际为 {row['condition']!r}。",
        ))
    if _parse_timestamp(row["occurred_at"]) is None:
        issues.append(Issue(
            line, "error", "invalid_timestamp",
            f"occurred_at 不是可解析的 ISO 8601 时间戳：{row['occurred_at']!r}。",
        ))
    if not isinstance(row.get("details", {}), dict):
        issues.append(Issue(
            line, "error", "invalid_details",
            "details 必须是 JSON 对象。",
        ))
    for name in ("goal_id", "job_id"):
        if row.get(name) is not None and not isinstance(row[name], str):
            issues.append(Issue(
                line, "error", "invalid_identifier",
                f"{name} 必须是字符串或 null。",
            ))
    return True


def _build_run(run_id: str, condition: str) -> RunSummary:
    return RunSummary(
        condition=condition,
        events=0,
        first_event="",
        last_event="",
        event_counts={},
        labels={},
        jobs={},
        delivery_methods={},
    )


def _track_job(
    run: RunSummary,
    row: dict[str, Any],
    line: int,
    issues: list[Issue],
) -> None:
    """累计委托生命周期，并报告不配对、重复终止等问题。"""
    name = row["name"]
    if name not in DELEGATION_LIFECYCLE:
        return

    job_id = row.get("job_id")
    if not job_id:
        issues.append(Issue(
            line, "error", "delegation_without_job_id",
            f"{name} 事件缺少 job_id。",
        ))
        return
    if run.condition not in ("I", "D"):
        issues.append(Issue(
            line, "error", "delegation_in_wrong_condition",
            f"{run.condition} 条件不应产生委托事件（{name}）。",
        ))

    trace = run.jobs.setdefault(job_id, JobTrace())
    field_name = name.removeprefix("delegation_")
    setattr(trace, field_name, getattr(trace, field_name) + 1)

    if name == "delegation_delivered":
        method = row.get("details", {}).get("method")
        run.delivery_methods[method] = run.delivery_methods.get(method, 0) + 1
        if method not in VALID_DELIVERY_METHODS:
            issues.append(Issue(
                line, "error", "invalid_delivery_method",
                f"未知的交付方式：{method!r}。",
            ))
        elif run.condition == "I" and method != "immediate":
            issues.append(Issue(
                line, "warning", "unexpected_delivery_method",
                f"I 条件应即时交付，实际方式为 {method!r}。",
            ))
        elif run.condition == "D" and method == "immediate":
            issues.append(Issue(
                line, "warning", "unexpected_delivery_method",
                "D 条件应在检查点或提前查看时交付，不应为 immediate。",
            ))


def _finalize_jobs(run: RunSummary, run_id: str, issues: list[Issue]) -> None:
    """在整份日志读取完后检查每个委托的最终状态。"""
    for job_id, trace in run.jobs.items():
        if trace.completed or trace.delivered or trace.cancelled or trace.failed:
            if trace.submitted == 0:
                issues.append(Issue(
                    0, "error", "missing_submission",
                    f"run {run_id!r} 的委托 {job_id!r} 没有 delegation_submitted。",
                ))
        if trace.delivered and trace.completed == 0:
            issues.append(Issue(
                0, "error", "delivered_without_completion",
                f"run {run_id!r} 的委托 {job_id!r} 已交付但未记录完成。",
            ))
        terminal = trace.delivered + trace.cancelled + trace.failed
        if terminal > 1:
            issues.append(Issue(
                0, "error", "multiple_terminal_events",
                f"run {run_id!r} 的委托 {job_id!r} 有 {terminal} 个终止事件。",
            ))
        if trace.completed > 1:
            issues.append(Issue(
                0, "warning", "duplicate_completion",
                f"run {run_id!r} 的委托 {job_id!r} 记录了多次完成。",
            ))


def check_events(path: str | Path) -> Report:
    """读取并校验一份事件 JSONL，返回结构化报告。"""
    source = Path(path)
    report = Report(path=str(source), total_events=0)
    runs: dict[str, RunSummary] = {}
    run_first_line: dict[str, int] = {}
    last_timestamp: dict[str, datetime] = {}

    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {source}：{exc}") from exc

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            report.issues.append(Issue(
                line_number, "error", "invalid_json",
                f"不是合法 JSON：{exc.msg}。",
            ))
            continue
        if not isinstance(row, dict):
            report.issues.append(Issue(
                line_number, "error", "invalid_row",
                "每行必须是 JSON 对象。",
            ))
            continue

        report.total_events += 1
        if not _validate_row(row, line_number, report.issues):
            continue

        run_id = row["run_id"]
        condition = row["condition"]
        run = runs.get(run_id)
        if run is None:
            run = _build_run(run_id, condition)
            runs[run_id] = run
            run_first_line[run_id] = line_number
        elif run.condition != condition:
            report.issues.append(Issue(
                line_number, "error", "mixed_condition",
                f"run {run_id!r} 混用了条件 {run.condition} 与 {condition}。",
            ))

        name = row["name"]
        occurred_at = row["occurred_at"]
        run.events += 1
        run.event_counts[name] = run.event_counts.get(name, 0) + 1
        if not run.first_event:
            run.first_event = occurred_at
        run.last_event = occurred_at

        timestamp = _parse_timestamp(occurred_at)
        if timestamp is not None:
            previous = last_timestamp.get(run_id)
            if previous is not None and timestamp < previous:
                report.issues.append(Issue(
                    line_number, "warning", "timestamp_out_of_order",
                    f"run {run_id!r} 的时间戳早于上一条事件。",
                ))
            last_timestamp[run_id] = timestamp

        if name == "activity_classified":
            label = row.get("details", {}).get("label")
            if label is not None and label not in VALID_LABELS:
                report.issues.append(Issue(
                    line_number, "warning", "unknown_activity_label",
                    f"未知的活动分类标签：{label!r}。",
                ))
            if label is not None:
                run.labels[label] = run.labels.get(label, 0) + 1

        _track_job(run, row, line_number, report.issues)

    for run_id, run in runs.items():
        _finalize_jobs(run, run_id, report.issues)
    report.runs = runs
    return report


def format_text(report: Report) -> str:
    """生成人类可读的摘要。"""
    lines = [
        f"文件：{report.path}",
        f"事件总数：{report.total_events}",
        f"run 数量：{len(report.runs)}",
    ]
    if report.runs:
        lines.append("")
        lines.append("各轮次摘要：")
        for run_id, run in report.runs.items():
            lines.append(
                f"  - {run_id}  条件={run.condition}  事件={run.events}  "
                f"委托={len(run.jobs)}  交付方式={run.delivery_methods or '无'}"
            )
            if run.labels:
                labels = ", ".join(f"{k}:{v}" for k, v in sorted(run.labels.items()))
                lines.append(f"      分类标签：{labels}")
    lines.append("")
    if report.issues:
        lines.append(f"发现问题：{report.error_count} 个错误，{report.warning_count} 个警告")
        for issue in report.issues:
            lines.append(f"  {issue.render()}")
    else:
        lines.append("未发现结构或流程问题。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验实验事件 JSONL 的结构与委托生命周期一致性。",
    )
    parser.add_argument("path", help="导出的 .jsonl 文件路径")
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="以 JSON 格式输出结果，便于脚本处理",
    )
    args = parser.parse_args(argv)

    try:
        report = check_events(args.path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.as_json else format_text(report))
    return 1 if report.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
