"""用固定 Prompt 与模型批量运行分类样本，输出指标和逐条结果。

    python -m intentaware.nlp.evaluate tests/fixtures/nlp_samples.jsonl
    python -m intentaware.nlp.evaluate tests/fixtures/nlp_samples.jsonl --json

开发样本（本仓库 40 条）与 E 模块的 60 条保留样本必须分开：本工具只用于
回归与错误分析，不能拿保留样本调 Prompt。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from intentaware.contracts import ActivityContext, ActivityLabel, Goal

from .classifier import LlmActivityClassifier
from .config import LlmConfig
from .errors import NlpConfigError, NlpError
from .llm import OpenAICompatibleClient


def load_samples(path: str | Path) -> list[dict]:
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            raise ValueError(f"样本第 {number} 行不是合法 JSON。") from None
    if not rows:
        raise ValueError("样本文件为空。")
    return rows


def context_from(sample: Mapping[str, object]) -> ActivityContext:
    return ActivityContext(
        goal=Goal(
            title=str(sample["goal_title"]),
            next_step=str(sample["goal_next_step"]),
        ),
        activity=str(sample["activity"]),
        progress=str(sample.get("progress", "")),
    )


def evaluate(classifier, samples: Sequence[Mapping[str, object]]) -> dict:
    rows = []
    for sample in samples:
        expected = str(sample["expected_label"])
        try:
            result = classifier.classify(context_from(sample))
            predicted = result.label.value
            reason = result.reason
        except NlpError as exc:
            predicted = "error"
            reason = str(exc)
        metadata = getattr(classifier, "metadata", None) or {}
        rows.append(
            {
                "id": sample.get("id", ""),
                "expected": expected,
                "predicted": predicted,
                "reason": reason,
                "activity": str(sample["activity"]),
                "usage": metadata.get("usage"),
                "latency_ms": metadata.get("latency_ms"),
            }
        )

    total = len(rows)
    correct = sum(1 for row in rows if row["expected"] == row["predicted"])
    labels = _per_label(rows)
    supported = [value for value in labels.values() if value["support"]]
    macro_f1 = (
        sum(value["f1"] for value in supported) / len(supported) if supported else 0.0
    )
    latencies = [row["latency_ms"] for row in rows if isinstance(row["latency_ms"], (int, float))]
    usage_totals: dict[str, int] = {}
    for row in rows:
        if isinstance(row["usage"], dict):
            for key, value in row["usage"].items():
                if isinstance(value, int) and not isinstance(value, bool):
                    usage_totals[key] = usage_totals.get(key, 0) + value
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "macro_f1": macro_f1,
        "labels": labels,
        "usage_totals": usage_totals,
        "latency_mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "errors": [row for row in rows if row["expected"] != row["predicted"]],
        "rows": rows,
    }


def _per_label(rows: Sequence[Mapping[str, str]]) -> dict[str, dict]:
    result = {}
    for item in ActivityLabel:
        label = item.value
        true_positive = sum(
            1 for row in rows if row["expected"] == label and row["predicted"] == label
        )
        support = sum(1 for row in rows if row["expected"] == label)
        predicted = sum(1 for row in rows if row["predicted"] == label)
        precision = true_positive / predicted if predicted else None
        recall = true_positive / support if support else None
        if not support:
            f1 = None
        elif precision is None or recall is None:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[label] = {
            "support": support,
            "predicted": predicted,
            "true_positive": true_positive,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return result


def _print_report(report: dict) -> None:
    print(f"样本数：{report['total']}  正确：{report['correct']}  准确率：{report['accuracy']:.3f}  Macro-F1：{report['macro_f1']:.3f}")
    print(f"{'label':<24}{'support':>8}{'precision':>11}{'recall':>8}{'f1':>7}")
    for label, value in report["labels"].items():
        precision = "—" if value["precision"] is None else f"{value['precision']:.3f}"
        recall = "—" if value["recall"] is None else f"{value['recall']:.3f}"
        f1 = "—" if value["f1"] is None else f"{value['f1']:.3f}"
        print(f"{label:<24}{value['support']:>8}{precision:>11}{recall:>8}{f1:>7}")
    if report["usage_totals"]:
        tokens = "  ".join(f"{key}={value}" for key, value in report["usage_totals"].items())
        print(f"\nToken 用量：{tokens}")
    if report["latency_mean_ms"] is not None:
        print(f"平均延迟：{report['latency_mean_ms']:.0f} ms")
    if report["errors"]:
        print("\n错误样本：")
        for row in report["errors"]:
            print(f"- {row['id']}: 期望 {row['expected']}，实际 {row['predicted']}｜{row['activity']}")


def build_classifier(env=None) -> LlmActivityClassifier:
    return LlmActivityClassifier(OpenAICompatibleClient(LlmConfig.from_env(env)))


def main(argv: list[str] | None = None, *, classifier=None) -> int:
    parser = argparse.ArgumentParser(description="批量运行活动分类样本并输出指标")
    parser.add_argument("samples", type=Path, help="JSONL 样本文件")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    args = parser.parse_args(argv)

    try:
        samples = load_samples(args.samples)
        provider = classifier or build_classifier()
    except NlpConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"样本错误：{exc}", file=sys.stderr)
        return 1

    report = evaluate(provider, samples)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
