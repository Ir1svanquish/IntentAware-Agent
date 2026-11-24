import json

from experiments.analyze_events import summarize_events
from experiments.baseline import classify_activity, load_samples, run_baseline
from experiments.metrics import macro_f1, false_alert_rate, summarize
from experiments.samples import check_isolation


def _sample(id_, activity, expected, goal="完成论文", step="写方法章节"):
    return {
        "id": id_,
        "goal_title": goal,
        "goal_next_step": step,
        "progress": "",
        "activity": activity,
        "expected_label": expected,
    }


def test_baseline_rules_and_low_information():
    assert classify_activity("刷短视频找撰写论文的灵感").label.value == "optional_exploration"
    assert classify_activity("查阅 FastAPI 官方文档").label.value == "necessary_preparation"
    assert classify_activity("撰写方法章节正文").label.value == "direct_progress"
    assert classify_activity("打开了一个窗口").label.value == "unclear"
    assert classify_activity("无意义的乱码").label.value == "unclear"


def test_baseline_load_and_run(tmp_path):
    path = tmp_path / "samples.jsonl"
    rows = [
        _sample("s1", "撰写方法章节正文", "direct_progress"),
        _sample("s2", "刷短视频", "optional_exploration"),
    ]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    samples = load_samples(path)
    details = run_baseline(samples)
    assert [d["predicted"] for d in details] == ["direct_progress", "optional_exploration"]


def test_load_samples_rejects_bad_input(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    try:
        load_samples(path)
    except ValueError:
        pass
    else:
        raise AssertionError("bad json should raise")

    path.write_text(json.dumps(_sample("s1", "写正文", "bad_label")) + "\n", encoding="utf-8")
    try:
        load_samples(path)
    except ValueError:
        pass
    else:
        raise AssertionError("bad label should raise")


def test_macro_f1_ignores_labels_without_support():
    details = [
        {"expected": "direct_progress", "predicted": "direct_progress"},
        {"expected": "direct_progress", "predicted": "unclear"},
        {"expected": "unclear", "predicted": "unclear"},
    ]
    # direct_progress: precision=1, recall=0.5 -> F1=0.667
    # unclear: 预测 2 次命中 1 次, precision=0.5 recall=1 -> F1=0.667
    # 两个有 support 的标签 F1 相同，Macro-F1 仍为 0.667
    assert abs(macro_f1(details) - 2 / 3) < 1e-9


def test_false_alert_rate_definition_and_zero_denominator():
    details = [
        {"id": "a", "expected": "direct_progress", "predicted": "optional_exploration"},
        {"id": "b", "expected": "direct_progress", "predicted": "direct_progress"},
        {"id": "c", "expected": "optional_exploration", "predicted": "unclear"},
    ]
    report = false_alert_rate(details)
    assert report["rate"] == 0.5
    assert report["false_alerts"] == 1
    assert report["should_not_alert"] == 2
    assert report["false_alert_ids"] == ["a"]

    empty = false_alert_rate([{"expected": "unclear", "predicted": "unclear"}])
    assert empty["rate"] is None


def test_summarize_includes_confusion_matrix():
    details = [
        {"expected": "direct_progress", "predicted": "direct_progress", "id": "1"},
        {"expected": "unclear", "predicted": "optional_exploration", "id": "2"},
    ]
    report = summarize(details)
    assert report["confusion_matrix"]["direct_progress"]["direct_progress"] == 1
    assert report["confusion_matrix"]["unclear"]["optional_exploration"] == 1
    assert report["total"] == 2


def test_sample_isolation_detects_overlaps():
    dev = [_sample("same", "写正文", "direct_progress")]
    hold = [
        _sample("same", "写正文", "direct_progress"),
        _sample("other", "查文档", "necessary_preparation"),
    ]
    report = check_isolation(dev, hold)
    assert not report["isolated"]
    assert report["duplicate_ids"] == ["same"]
    assert report["duplicate_activity_count"] == 1

    clean_hold = [_sample("h1", "完全不同的活动", "unclear")]
    assert check_isolation(dev, clean_hold)["isolated"]


def test_events_delegation_and_resume_without_fabricating_endpoint():
    events = [
        {"run_id": "r1", "condition": "D", "name": "delegation_submitted", "job_id": "j1", "occurred_at": "2026-08-12T10:00:00+00:00"},
        {"run_id": "r1", "condition": "D", "name": "delegation_completed", "job_id": "j1", "occurred_at": "2026-08-12T10:00:02+00:00"},
        {"run_id": "r1", "condition": "D", "name": "delegation_delivered", "job_id": "j1", "details": {"method": "checkpoint"}, "occurred_at": "2026-08-12T10:00:07+00:00"},
        {"run_id": "r1", "condition": "D", "name": "resume_requested", "occurred_at": "2026-08-12T10:00:10+00:00"},
    ]
    report = summarize_events(events)
    assert report["delegation"]["processing_seconds"]["mean"] == 2.0
    assert report["delegation"]["delivery_seconds"]["mean"] == 5.0
    assert report["delegation"]["delivery_methods"] == {"checkpoint": 1}
    assert report["resume"]["measured"] is None
    assert report["resume"]["unresolved_count"] == 1

    with_edit = events + [{
        "run_id": "r1", "condition": "D", "name": "effective_edit",
        "occurred_at": "2026-08-12T10:00:13+00:00",
    }]
    measured = summarize_events(with_edit)["resume"]
    assert measured["measured"]["mean"] == 3.0
    assert measured["unresolved_count"] == 0


def test_resume_endpoint_must_share_run_id():
    events = [
        {"run_id": "r1", "condition": "D", "name": "resume_requested", "occurred_at": "2026-08-12T10:00:00+00:00"},
        {"run_id": "r2", "condition": "D", "name": "effective_edit", "occurred_at": "2026-08-12T10:00:01+00:00"},
    ]
    report = summarize_events(events)
    assert report["resume"]["measured"] is None
    assert report["resume"]["unresolved_count"] == 1
