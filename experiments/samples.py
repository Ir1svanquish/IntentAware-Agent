"""样本集划分与隔离校验。

Proposal 要求把 60 条任务上下文样本用于正式评估、40 条委托请求独立保留，
并与 B 模块的开发样本分开调 Prompt。本模块提供机械隔离检查：

- ID 不得重复；
- 活动描述不得逐字重复（避免同一条样本出现在开发集和保留集）；
- 目标 + 活动组合不得重复（捕捉改写了 ID 但内容相同的样本）。

注意：这只检查字面隔离。语义近似、来源污染与评审一致性需人工判断。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .baseline import load_samples


def _normalize(text: str) -> str:
    return "".join(text.split()).casefold()


def check_isolation(
    development: Sequence[Mapping[str, Any]],
    holdout: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """比较开发集与保留集，返回隔离检查结果。"""
    dev_ids = {str(row["id"]) for row in development}
    hold_ids = {str(row["id"]) for row in holdout}

    dev_activities: dict[str, list[str]] = {}
    hold_activities: dict[str, list[str]] = {}
    for row in development:
        dev_activities.setdefault(_normalize(str(row["activity"])), []).append(str(row["id"]))
    for row in holdout:
        hold_activities.setdefault(_normalize(str(row["activity"])), []).append(str(row["id"]))

    def pair(row: Mapping[str, Any]) -> str:
        return _normalize(f"{row.get('goal_title', '')}|{row.get('activity', '')}")

    dev_pairs = {pair(row) for row in development}
    hold_pairs = {pair(row) for row in holdout}

    duplicate_ids = sorted(dev_ids & hold_ids)
    duplicate_activities = sorted(set(dev_activities) & set(hold_activities))
    duplicate_pairs = sorted(dev_pairs & hold_pairs)

    issues = []
    if duplicate_ids:
        issues.append(f"ID 重叠：{', '.join(duplicate_ids)}")
    if duplicate_activities:
        issues.append(f"活动描述重复：{len(duplicate_activities)} 条")
    if duplicate_pairs:
        issues.append(f"目标+活动组合重复：{len(duplicate_pairs)} 条")

    return {
        "development_count": len(development),
        "holdout_count": len(holdout),
        "duplicate_ids": duplicate_ids,
        "duplicate_activity_count": len(duplicate_activities),
        "duplicate_pair_count": len(duplicate_pairs),
        "isolated": not issues,
        "issues": issues,
        "note": "字面隔离检查，不替代语义近似与评审一致性的人工判断。",
    }


def check_files(development_path: str, holdout_path: str) -> dict[str, Any]:
    """从两个 JSONL 文件加载样本并做隔离检查。"""
    return check_isolation(load_samples(development_path), load_samples(holdout_path))


def load_delegation_requests(path: str) -> list[dict]:
    """加载保留委托请求 JSONL。

    每行至少包含 id 与 question；答复、来源与引用支持由评估者另表填写，
    避免把模型输出混进保留集。
    """
    from pathlib import Path
    import json

    rows: list[dict] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise ValueError(f"委托请求第 {number} 行不是合法 JSON。") from None
        if not isinstance(row, dict) or "id" not in row or "question" not in row:
            raise ValueError(f"委托请求第 {number} 行缺少 id 或 question。")
        rows.append(row)
    if not rows:
        raise ValueError("委托请求文件为空。")
    return rows


__all__ = ["check_isolation", "check_files", "load_delegation_requests"]
