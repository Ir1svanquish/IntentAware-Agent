import json

from experiments.check_events import check_events, format_text


def _write(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _event(name, *, run="run-1", condition="D", job=None, details=None, at="2026-08-12T10:00:00.000+00:00"):
    return {
        "id": f"event-{name}-{job or ''}",
        "run_id": run,
        "condition": condition,
        "name": name,
        "goal_id": "goal-1",
        "job_id": job,
        "details": details or {},
        "occurred_at": at,
    }


def test_valid_export_produces_summary_without_issues(tmp_path):
    path = _write(tmp_path / "ok.jsonl", [
        _event("session_started", at="2026-08-12T10:00:00.000+00:00"),
        _event("activity_classified", details={"label": "direct_progress"}, at="2026-08-12T10:00:01.000+00:00"),
        _event("delegation_submitted", job="job-1", at="2026-08-12T10:00:02.000+00:00"),
        _event("delegation_completed", job="job-1", at="2026-08-12T10:00:03.000+00:00"),
        _event("delegation_delivered", job="job-1", details={"method": "checkpoint"}, at="2026-08-12T10:00:04.000+00:00"),
    ])
    report = check_events(path)

    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.total_events == 5
    assert report.runs["run-1"].condition == "D"
    assert report.runs["run-1"].event_counts["delegation_delivered"] == 1
    assert report.runs["run-1"].labels == {"direct_progress": 1}
    assert report.runs["run-1"].jobs["job-1"].as_dict() == {
        "submitted": 1, "completed": 1, "delivered": 1,
        "cancelled": 0, "failed": 0,
    }
    assert report.runs["run-1"].delivery_methods == {"checkpoint": 1}


def test_reports_missing_fields_and_invalid_values(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text(
        "not json\n"
        + json.dumps(_event("session_started", condition="X")) + "\n"
        + json.dumps(_event("activity_classified", at="not-a-date")) + "\n"
        + json.dumps({"name": "goal_saved"}) + "\n",
        encoding="utf-8",
    )
    report = check_events(path)
    codes = {issue.code for issue in report.issues}

    assert {"invalid_json", "invalid_condition", "invalid_timestamp", "missing_field"} <= codes
    assert report.error_count >= 4
    assert "第 1 行" in format_text(report)


def test_flags_incomplete_delegation_lifecycle(tmp_path):
    path = _write(tmp_path / "job.jsonl", [
        _event("delegation_completed", job="orphan"),
        _event("delegation_delivered", job="orphan", details={"method": "checkpoint"}),
    ])
    report = check_events(path)
    codes = {issue.code for issue in report.issues}

    assert "missing_submission" in codes
    assert "delivered_without_completion" not in codes


def test_flags_multiple_terminal_events_and_wrong_condition(tmp_path):
    path = _write(tmp_path / "job.jsonl", [
        _event("delegation_submitted", job="job-1", condition="G"),
        _event("delegation_completed", job="job-1", condition="G"),
        _event("delegation_delivered", job="job-1", condition="G", details={"method": "immediate"}),
        _event("delegation_cancelled", job="job-1", condition="G"),
    ])
    report = check_events(path)
    codes = {issue.code for issue in report.issues}

    assert "delegation_in_wrong_condition" in codes
    assert "multiple_terminal_events" in codes


def test_warns_on_unexpected_delivery_method_and_out_of_order_time(tmp_path):
    path = _write(tmp_path / "warn.jsonl", [
        _event("delegation_submitted", job="job-1", condition="I", at="2026-08-12T10:00:02.000+00:00"),
        _event("delegation_completed", job="job-1", condition="I", at="2026-08-12T10:00:03.000+00:00"),
        _event("delegation_delivered", job="job-1", condition="I", details={"method": "checkpoint"}, at="2026-08-12T10:00:01.000+00:00"),
    ])
    report = check_events(path)
    codes = {issue.code for issue in report.issues}

    assert report.error_count == 0
    assert {"unexpected_delivery_method", "timestamp_out_of_order"} <= codes


def test_mixed_condition_in_one_run_is_an_error(tmp_path):
    path = _write(tmp_path / "mixed.jsonl", [
        _event("session_started", condition="G"),
        _event("resume_requested", condition="P"),
    ])
    report = check_events(path)

    assert any(issue.code == "mixed_condition" for issue in report.issues)


def test_empty_file_and_missing_file(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    report = check_events(empty)
    assert report.total_events == 0
    assert report.error_count == 0

    try:
        check_events(tmp_path / "missing.jsonl")
    except ValueError as exc:
        assert "无法读取" in str(exc)
    else:
        raise AssertionError("missing file should raise ValueError")
