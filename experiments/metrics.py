"""分类评估指标：Macro-F1 与误提醒率。

Macro-F1 的口径与 B 模块 ``nlp/evaluate.py`` 保持一致（只对有 support
的标签求平均），便于两个模块的结果直接对照。误提醒率是 E 模块新增的
指标：在 G 条件的目标提醒里，把"实际在推进任务、却被判为分心/不确定"
当作一次误提醒。

注意：本模块只做机械计算。分类样本的人工标注、两名评审核查和
12–18 人组内实验需由研究者按伦理流程完成，本模块不生成也不伪造数据。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

DIRECT_LABELS = frozenset({"direct_progress", "necessary_preparation"})
DISTRACTION_LABELS = frozenset({"optional_exploration", "unclear"})
VALID_LABELS = frozenset({
    "direct_progress", "necessary_preparation", "optional_exploration", "unclear",
})
LABEL_ORDER = (
    "direct_progress", "necessary_preparation", "optional_exploration", "unclear",
)
UNCLEAR = "unclear"


def per_label(details: Sequence[Mapping[str, str]]) -> dict[str, dict]:
    """逐标签统计 support / precision / recall / F1。"""
    result: dict[str, dict] = {}
    rows = list(details)
    for label in LABEL_ORDER:
        tp = sum(1 for r in rows if r["expected"] == label and r["predicted"] == label)
        support = sum(1 for r in rows if r["expected"] == label)
        predicted = sum(1 for r in rows if r["predicted"] == label)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        if not support:
            f1 = None
        elif precision is None or recall is None:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[label] = {
            "support": support,
            "predicted": predicted,
            "true_positive": tp,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return result


def macro_f1(details: Sequence[Mapping[str, str]]) -> float:
    """只对有样本的标签求 F1 平均，与 B 模块口径一致。"""
    labels = per_label(details)
    supported = [value["f1"] for value in labels.values() if value.get("support")]
    return sum(supported) / len(supported) if supported else 0.0


def confusion_matrix(details: Sequence[Mapping[str, str]]) -> dict[str, dict[str, int]]:
    """返回 expected -> predicted -> 数量 的混淆矩阵。"""
    matrix = {label: {other: 0 for other in LABEL_ORDER} for label in LABEL_ORDER}
    for row in details:
        if row["expected"] in matrix and row["predicted"] in matrix[row["expected"]]:
            matrix[row["expected"]][row["predicted"]] += 1
    return matrix


def false_alert_rate(details: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """计算误提醒率及口径说明。

    误提醒定义：expected 属于 DIRECT_LABELS（实际在推进任务），
    但 predicted 属于 DISTRACTION_LABELS（被判为分心或不确定），
    从而可能触发一次不必要的目标提醒。

    分母：所有 expected 属于 DIRECT_LABELS 的样本数（本应不提醒的场景）。
    若分母为 0 返回 None，避免除零。
    """
    rows = list(details)
    should_not_alert = [r for r in rows if r["expected"] in DIRECT_LABELS]
    false_alerts = [
        r for r in should_not_alert if r["predicted"] in DISTRACTION_LABELS
    ]
    denominator = len(should_not_alert)
    rate = len(false_alerts) / denominator if denominator else None

    # 参考口径：在所有"被判为分心"的样本中，有多少是误判。
    predicted_alert = [r for r in rows if r["predicted"] in DISTRACTION_LABELS]
    alert_precision = None
    if predicted_alert:
        true_alerts = sum(1 for r in predicted_alert if r["expected"] in DISTRACTION_LABELS)
        alert_precision = true_alerts / len(predicted_alert)

    return {
        "rate": rate,
        "false_alerts": len(false_alerts),
        "should_not_alert": denominator,
        "alert_precision": alert_precision,
        "definition": (
            "误提醒 = expected∈{direct_progress,necessary_preparation} "
            "且 predicted∈{optional_exploration,unclear}；"
            "分母为 expected∈{direct_progress,necessary_preparation} 的样本数。"
        ),
        "false_alert_ids": [str(r.get("id", "")) for r in false_alerts],
    }


def summarize(details: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """汇总分类指标，供 CLI 与报告复用。"""
    rows = [{"expected": r["expected"], "predicted": r["predicted"], "id": r.get("id", "")}
            for r in details]
    total = len(rows)
    correct = sum(1 for r in rows if r["expected"] == r["predicted"])
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "macro_f1": macro_f1(rows),
        "labels": per_label(rows),
        "confusion_matrix": confusion_matrix(rows),
        "false_alert": false_alert_rate(rows),
    }


__all__ = [
    "DIRECT_LABELS", "DISTRACTION_LABELS", "VALID_LABELS", "LABEL_ORDER", "UNCLEAR",
    "per_label", "macro_f1", "confusion_matrix", "false_alert_rate", "summarize",
]
