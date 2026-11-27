"""D 模块批量评测 CLI：运行留出委托请求样本，统计耗时、Token 与评估表草稿。

    python -m intentaware.delegation.evaluate experiments/data/holdout_delegations.jsonl --limit 5
    python -m intentaware.delegation.evaluate experiments/data/holdout_delegations.jsonl --out-csv out.csv
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import csv
import json
from pathlib import Path
import sys
from threading import Event

from intentaware.nlp.config import LlmConfig
from intentaware.nlp.errors import NlpConfigError

from .agent import LiveDelegator
from .config import DelegationConfig
from .errors import DelegationConfigError, DelegationError
from .retriever import PublicWebRetriever

EVAL_CSV_HEADERS = (
    "id",
    "question",
    "topic",
    "sources_count",
    "source_1_url",
    "source_2_url",
    "citation_supported",
    "answer_quality_1_5",
    "unresolved_points",
    "evaluator",
)


def load_delegation_samples(path: str | Path) -> list[dict]:
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise ValueError(f"委托样本第 {number} 行不是合法 JSON。") from None
        if not isinstance(row, dict) or not str(row.get("question") or "").strip():
            raise ValueError(f"委托样本第 {number} 行缺少 question 字段。")
        rows.append(row)
    if not rows:
        raise ValueError("委托样本文件为空。")
    return rows


def _extract_unresolved(answer: str) -> str:
    marker = "未解决的部分"
    if marker not in answer:
        return ""
    section = answer.split(marker, 1)[1].strip().split("\n\n", 1)[0]
    lines = [line.lstrip("- ").strip() for line in section.splitlines() if line.strip()]
    return "；".join(lines[:3])


def evaluate(delegator, samples: Sequence[Mapping[str, object]]) -> dict:
    rows = []
    for sample in samples:
        sample_id = str(sample.get("id", ""))
        question = str(sample["question"])
        topic = str(sample.get("topic", ""))
        try:
            result = delegator.run(question, Event())
            metrics = (
                delegator.pop_job_metrics(question)
                if hasattr(delegator, "pop_job_metrics")
                else {}
            )
            urls = [source.url for source in result.sources[:2]]
            rows.append(
                {
                    "id": sample_id,
                    "question": question,
                    "topic": topic,
                    "status": "ok",
                    "answer": result.answer,
                    "sources_count": len(result.sources),
                    "source_1_url": urls[0] if len(urls) > 0 else "",
                    "source_2_url": urls[1] if len(urls) > 1 else "",
                    "unresolved_points": _extract_unresolved(result.answer),
                    "error": "",
                    "latency_ms": metrics.get("latency_ms"),
                    "usage": metrics.get("usage"),
                }
            )
        except (DelegationError, ValueError, RuntimeError) as exc:
            rows.append(
                {
                    "id": sample_id,
                    "question": question,
                    "topic": topic,
                    "status": "error",
                    "answer": "",
                    "sources_count": 0,
                    "source_1_url": "",
                    "source_2_url": "",
                    "unresolved_points": "",
                    "error": str(exc),
                    "latency_ms": None,
                    "usage": None,
                }
            )

    total = len(rows)
    succeeded = sum(1 for row in rows if row["status"] == "ok")
    failed = total - succeeded
    source_counts = [row["sources_count"] for row in rows if row["status"] == "ok"]
    latencies = [row["latency_ms"] for row in rows if isinstance(row["latency_ms"], (int, float))]
    usage_totals: dict[str, int] = {}
    for row in rows:
        if isinstance(row["usage"], dict):
            for key, value in row["usage"].items():
                if isinstance(value, int) and not isinstance(value, bool):
                    usage_totals[key] = usage_totals.get(key, 0) + value

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "avg_sources": sum(source_counts) / len(source_counts) if source_counts else 0.0,
        "latency_mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "usage_totals": usage_totals,
        "rows": rows,
    }


def write_eval_csv(rows: Sequence[Mapping[str, object]], out_csv: str | Path) -> Path:
    """导出与 experiments/data/delegation_eval_sheet.csv 对齐的空白人工评分表。"""
    target = Path(out_csv)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVAL_CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": row.get("id", ""),
                    "question": row.get("question", ""),
                    "topic": row.get("topic", ""),
                    "sources_count": row.get("sources_count", 0),
                    "source_1_url": row.get("source_1_url", ""),
                    "source_2_url": row.get("source_2_url", ""),
                    "citation_supported": "",
                    "answer_quality_1_5": "",
                    "unresolved_points": row.get("unresolved_points", ""),
                    "evaluator": "",
                }
            )
    return target


def build_delegator(env=None) -> LiveDelegator:
    llm_config = LlmConfig.from_env(env)
    delegation_config = DelegationConfig.from_env(env)
    return LiveDelegator(
        llm_config,
        PublicWebRetriever(delegation_config),
        config=delegation_config,
    )


def _print_report(report: dict) -> None:
    print(
        f"样本数：{report['total']}  成功：{report['succeeded']}  "
        f"失败：{report['failed']}  平均来源数：{report['avg_sources']:.2f}"
    )
    if report["latency_mean_ms"] is not None:
        print(f"平均延迟：{report['latency_mean_ms']:.0f} ms")
    if report["usage_totals"]:
        tokens = "  ".join(f"{k}={v}" for k, v in report["usage_totals"].items())
        print(f"Token 用量：{tokens}")
    failures = [row for row in report["rows"] if row["status"] != "ok"]
    if failures:
        print("\n失败样本：")
        for row in failures:
            print(f"- {row['id']}: {row['error']}")


def main(argv: list[str] | None = None, *, delegator=None) -> int:
    parser = argparse.ArgumentParser(description="批量运行委托样本并输出延迟、Token 与评估草稿")
    parser.add_argument("samples", type=Path, help="JSONL 委托样本文件")
    parser.add_argument("--limit", type=int, default=0, help="仅运行前 N 条样本（默认全部）")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    parser.add_argument("--out-csv", type=Path, help="导出供人工核查的评估 CSV 路径")
    args = parser.parse_args(argv)

    try:
        samples = load_delegation_samples(args.samples)
        if args.limit and args.limit > 0:
            samples = samples[: args.limit]
        provider = delegator or build_delegator()
    except (DelegationConfigError, NlpConfigError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"样本错误：{exc}", file=sys.stderr)
        return 1

    report = evaluate(provider, samples)
    if args.out_csv:
        write_eval_csv(report["rows"], args.out_csv)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
