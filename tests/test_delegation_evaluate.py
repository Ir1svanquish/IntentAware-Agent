"""D 模块批量评测 CLI 测试：样本加载、汇总统计与评估 CSV 导出。"""

import csv
import json

from intentaware.contracts import DelegationResult, Source
from intentaware.delegation.evaluate import main


def test_delegation_evaluate_cli_writes_json_and_csv(tmp_path, capsys):
    samples_path = tmp_path / "samples.jsonl"
    samples_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "d-01", "question": "什么是 Macro-F1？", "topic": "评估"}, ensure_ascii=False),
                json.dumps({"id": "d-02", "question": "失败样本问题", "topic": "异常"}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )

    class StubDelegator:
        def __init__(self):
            self._metrics = {}

        def run(self, question, cancel):
            if "失败" in question:
                raise RuntimeError("模拟检索失败")
            self._metrics[question] = {
                "latency_ms": 120.0,
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            }
            return DelegationResult(
                answer="Macro-F1 对各类别平等求平均。\n\n未解决的部分\n- 未讨论极度不平衡样本下的方差。",
                sources=(Source("Scikit-learn Metrics", "https://scikit-learn.org/stable/modules/model_evaluation.html"),),
            )

        def pop_job_metrics(self, question):
            return self._metrics.pop(question, {})

    out_csv = tmp_path / "eval.csv"
    exit_code = main(
        [str(samples_path), "--json", "--out-csv", str(out_csv)],
        delegator=StubDelegator(),
    )
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 2
    assert payload["succeeded"] == 1
    assert payload["failed"] == 1
    assert payload["usage_totals"]["total_tokens"] == 70
    assert payload["latency_mean_ms"] == 120.0

    with out_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["id"] == "d-01"
    assert rows[0]["sources_count"] == "1"
    assert rows[0]["source_1_url"].startswith("https://scikit-learn.org")
    assert rows[0]["citation_supported"] == ""
    assert rows[0]["answer_quality_1_5"] == ""
    assert rows[0]["evaluator"] == ""
    assert "方差" in rows[0]["unresolved_points"]


def test_extract_unresolved_excludes_verification_section():
    from intentaware.delegation.evaluate import _extract_unresolved

    answer = (
        "核心结论。\n\n"
        "未解决的部分\n- 未对比最新 Python 3.13 特性\n\n"
        "引用核验说明\n- 已过滤 1 条未能核实的引用。"
    )
    extracted = _extract_unresolved(answer)
    assert "未对比最新 Python 3.13 特性" in extracted
    assert "引用核验说明" not in extracted
    assert "已过滤" not in extracted
