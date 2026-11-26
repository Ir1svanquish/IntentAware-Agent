"""40 条开发样本的结构、四类平衡与"样本 → 分类器 → 共享结构"链路。

这里验证的是链路与标注契约，不代表真实模型准确率；真实模型评估使用
``python -m intentaware.nlp.evaluate``。开发样本与 E 的 60 条保留样本隔离。
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from intentaware.contracts import ActivityContext, ActivityLabel, Goal
from intentaware.nlp.classifier import LlmActivityClassifier
from intentaware.nlp.evaluate import evaluate, load_samples
from intentaware.nlp.evaluate import main as evaluate_main
from intentaware.nlp.llm import FakeLLMClient

SAMPLES = Path(__file__).resolve().parent / "fixtures" / "nlp_samples.jsonl"
REQUIRED_FIELDS = {
    "id",
    "goal_title",
    "goal_next_step",
    "progress",
    "activity",
    "expected_label",
    "note",
}


def samples():
    return load_samples(SAMPLES)


def context(sample):
    return ActivityContext(
        Goal(sample["goal_title"], sample["goal_next_step"]),
        sample["activity"],
        sample["progress"],
    )


def payload_for(sample):
    return {
        "label": sample["expected_label"],
        "reason": "测试理由",
        "suggested_next_step": "测试下一步",
    }


def test_fixture_has_40_unique_samples_balanced_across_labels():
    rows = samples()

    assert len(rows) == 40
    assert len({row["id"] for row in rows}) == 40
    for row in rows:
        assert REQUIRED_FIELDS <= set(row)
        assert row["activity"].strip()
    assert Counter(row["expected_label"] for row in rows) == {
        label.value: 10 for label in ActivityLabel
    }


@pytest.mark.parametrize("sample", samples(), ids=lambda row: row["id"])
def test_every_sample_maps_to_its_expected_label(sample):
    classifier = LlmActivityClassifier(FakeLLMClient([payload_for(sample)]))

    assert classifier.classify(context(sample)).label.value == sample["expected_label"]


def test_same_activity_flips_label_when_goal_context_changes():
    direct = next(row for row in samples() if row["id"] == "dev-005")
    preparation = next(row for row in samples() if row["id"] == "dev-012")

    assert direct["activity"] == preparation["activity"] == "阅读第三章"
    assert direct["goal_title"] != preparation["goal_title"]
    assert direct["expected_label"] == "direct_progress"
    assert preparation["expected_label"] == "necessary_preparation"


def test_leisure_activity_with_topic_keyword_is_not_direct_progress():
    sample = next(row for row in samples() if row["id"] == "dev-021")

    assert "论文" in sample["activity"]
    assert sample["expected_label"] == "optional_exploration"


def test_evaluate_computes_accuracy_errors_and_per_label_scores():
    rows = [
        {
            "id": "a",
            "goal_title": "完成论文",
            "goal_next_step": "写正文",
            "progress": "",
            "activity": "写正文",
            "expected_label": "direct_progress",
        },
        {
            "id": "b",
            "goal_title": "完成论文",
            "goal_next_step": "写正文",
            "progress": "",
            "activity": "刷视频",
            "expected_label": "unclear",
        },
    ]
    classifier = LlmActivityClassifier(
        FakeLLMClient(
            [
                {"label": "direct_progress", "reason": "在写", "suggested_next_step": "继续"},
                {"label": "optional_exploration", "reason": "休闲", "suggested_next_step": "先记下"},
            ]
        )
    )

    report = evaluate(classifier, rows)

    assert report["total"] == 2
    assert report["correct"] == 1
    assert report["accuracy"] == 0.5
    assert [row["id"] for row in report["errors"]] == ["b"]
    assert report["labels"]["direct_progress"]["f1"] == 1.0
    assert report["labels"]["unclear"]["support"] == 1
    assert report["labels"]["unclear"]["f1"] == 0.0
    assert report["usage_totals"] == {}
    assert report["latency_mean_ms"] is None


def test_evaluate_aggregates_token_usage_and_latency():
    class UsageClient(FakeLLMClient):
        def complete_json(self, **kwargs):
            result = super().complete_json(**kwargs)
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 2}
            self.last_latency_ms = 200.0
            return result

    rows = [
        {
            "id": "u-1",
            "goal_title": "完成论文",
            "goal_next_step": "写正文",
            "progress": "",
            "activity": "写正文",
            "expected_label": "direct_progress",
        }
    ]
    classifier = LlmActivityClassifier(
        UsageClient(
            [{"label": "direct_progress", "reason": "在写", "suggested_next_step": "继续"}]
        )
    )

    report = evaluate(classifier, rows)

    assert report["usage_totals"] == {"prompt_tokens": 10, "completion_tokens": 2}
    assert report["latency_mean_ms"] == 200.0
    assert report["rows"][0]["usage"]["prompt_tokens"] == 10


def test_evaluate_cli_runs_offline_and_prints_report(tmp_path, capsys):
    path = tmp_path / "samples.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "t-1",
                "goal_title": "完成报告",
                "goal_next_step": "写结论",
                "progress": "",
                "activity": "写结论",
                "expected_label": "direct_progress",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    classifier = LlmActivityClassifier(
        FakeLLMClient(
            [{"label": "direct_progress", "reason": "在写结论", "suggested_next_step": "继续"}]
        )
    )

    assert evaluate_main([str(path)], classifier=classifier) == 0
    out = capsys.readouterr().out
    assert "准确率" in out
    assert "direct_progress" in out
