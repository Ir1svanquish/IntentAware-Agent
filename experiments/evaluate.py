"""E 模块统一评估入口。

子命令：
    baseline  对保留样本跑关键词基线，输出 Macro-F1、混淆矩阵与误提醒率
    events    从事件 JSONL 计算委托延迟与恢复时间
    isolate   校验开发集与保留集的字面隔离
    check     事件 JSONL 的结构与委托生命周期自检

用法（仓库根目录）：
    python -m experiments.evaluate baseline experiments/data/holdout_contexts.jsonl
    python -m experiments.evaluate events events.jsonl --json
    python -m experiments.evaluate isolate dev.jsonl holdout.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze_events import load_events, summarize_events
from .baseline import load_samples, run_baseline
from .check_events import check_events, format_text
from .metrics import summarize
from .samples import check_files


def _print_baseline(report: dict) -> None:
    false_alert = report["false_alert"]
    print(
        f"样本数：{report['total']}  正确：{report['correct']}  "
        f"准确率：{report['accuracy']:.3f}  Macro-F1：{report['macro_f1']:.3f}"
    )
    if false_alert["rate"] is not None:
        print(
            f"误提醒率：{false_alert['rate']:.3f} "
            f"（{false_alert['false_alerts']}/{false_alert['should_not_alert']}）"
        )
    else:
        print("误提醒率：不可计算（没有本应不提醒的样本）")
    print(f"\n{false_alert['definition']}")
    print("\n混淆矩阵（行=实际，列=预测）：")
    header = "".join(f"{label[:8]:>12}" for label in report["labels"])
    print(f"{'':<24}{header}")
    for expected, predicted in report["confusion_matrix"].items():
        cells = "".join(f"{count:>12}" for count in predicted.values())
        print(f"{expected:<24}{cells}")
    if false_alert["false_alert_ids"]:
        print(f"\n误提醒样本 ID：{', '.join(false_alert['false_alert_ids'])}")


def _print_events(report: dict) -> None:
    delegation = report["delegation"]
    resume = report["resume"]
    print(f"事件数：{report['total_events']}  run：{', '.join(report['run_ids']) or '无'}")
    print(f"条件分布：{report['condition_counts']}")
    print("\n委托：")
    print(f"  提交 {delegation['jobs_submitted']} / 完成 {delegation['jobs_completed']} / 交付 {delegation['jobs_delivered']}")
    for name in ("processing_seconds", "delivery_seconds"):
        stats = delegation[name]
        if stats:
            print(f"  {name}: n={stats['n']} mean={stats['mean']:.1f}s median={stats['median']:.1f}s")
        else:
            print(f"  {name}: 无数据")
    print(f"  交付方式：{delegation['delivery_methods'] or '无'}")
    if delegation.get("excluded_from_delivery"):
        print(f"  缺完成时间、已从交付延迟排除：{', '.join(delegation['excluded_from_delivery'])}")
    print("\n恢复时间：")
    if resume["measured"]:
        stats = resume["measured"]
        print(f"  已测 n={stats['n']} mean={stats['mean']:.1f}s median={stats['median']:.1f}s")
    else:
        print("  无可计算样本")
    print(f"  支线提示 {resume['prompt_count']} 次 / 点击恢复 {resume['resume_click_count']} 次（点击不计入计时）")
    if resume["missing_start_count"]:
        print(f"  {resume['missing_start_count']} 条有效编辑缺少起点，未计入")
    if resume["missing_end_count"]:
        print(f"  {resume['missing_end_count']} 条支线提示缺少有效编辑终点，未计入")
    print(f"\n{resume['start_definition']}")
    print(resume["endpoint_definition"])


def _print_isolation(report: dict) -> None:
    print(f"开发集 {report['development_count']} 条，保留集 {report['holdout_count']} 条")
    if report["isolated"]:
        print("字面隔离检查通过。")
    else:
        print("隔离检查未通过：")
        for issue in report["issues"]:
            print(f"  - {issue}")
    print(f"\n{report['note']}")


def _emit(data: dict, as_json: bool, printer) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        printer(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E 模块实验评估工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_baseline = sub.add_parser("baseline", help="对保留样本跑关键词基线")
    p_baseline.add_argument("samples", type=Path, help="JSONL 样本文件")
    p_baseline.add_argument("--json", action="store_true")

    p_events = sub.add_parser("events", help="从事件日志计算委托延迟与恢复时间")
    p_events.add_argument("events", type=Path, help="事件 JSONL 文件")
    p_events.add_argument("--json", action="store_true")

    p_isolate = sub.add_parser("isolate", help="校验开发集与保留集隔离")
    p_isolate.add_argument("development", type=Path)
    p_isolate.add_argument("holdout", type=Path)
    p_isolate.add_argument("--json", action="store_true")

    p_check = sub.add_parser("check", help="事件 JSONL 结构与生命周期自检")
    p_check.add_argument("events", type=Path)
    p_check.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "baseline":
            samples = load_samples(args.samples)
            report = summarize(run_baseline(samples))
            _emit(report, args.json, _print_baseline)
            return 0
        if args.command == "events":
            report = summarize_events(load_events(args.events))
            _emit(report, args.json, _print_events)
            return 0
        if args.command == "isolate":
            report = check_files(str(args.development), str(args.holdout))
            _emit(report, args.json, _print_isolation)
            return 0 if report["isolated"] else 1
        if args.command == "check":
            report = check_events(args.events)
            if args.json:
                print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            else:
                print(format_text(report))
            return 1 if report.error_count else 0
    except ValueError as exc:
        print(f"输入错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
