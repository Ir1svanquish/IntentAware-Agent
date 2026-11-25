Language / 语言：[简体中文](README.md) | **English**

# Experiments

Retain the proposal's **G/P/I/D** conditions, **60 task-context examples** with two reviewers, **40 held-out delegation requests**, and planned within-participant study with **12–18 adults**. The research has not been completed. Begin preparation in week 1 and satisfy consent and ethics requirements before participant testing.

The desktop observes application names and window titles, then uses local rules to infer tasks and classify activities. `--demo` supplies simulated observations, and delegation remains an offline demonstration. Record the platform, observation mode, and rule or model version. Keep demo data separate from formal evaluation and keep development examples separate from held-out examples.

| Evaluation area | Planned measures or records |
| --- | --- |
| Activity classification | Keyword baseline, macro-F1, false-warning rate; examine uncertainty and human corrections |
| Task performance | Completion, output quality, and time to resume the main task |
| Delegation | Answer quality, source and citation support, and unresolved points |
| Burden and cost | Perceived burden, latency, and token usage; local rules and offline examples do not constitute live-model evaluation |

The experiment page exports JSONL for the current `run_id`. Use `job_id` to distinguish `delegation_completed` (ready in the background) from `delegation_delivered` (delivered). The resume button logs `resume_requested` for counting clicks.

Raw ongoing window titles are not appended to event exports. Automatically seeded and user-edited task titles are saved in local task records. Avoid identifiable personal data in study records, and review explicitly saved task, progress, and detour content before sharing.

## Evaluation tools

Run the CLI from the repository root. These commands use the Python standard library. Add `--json` for machine-readable output.

```bash
python -m experiments.evaluate check events.jsonl
python -m experiments.evaluate events events.jsonl
python -m experiments.evaluate baseline experiments/data/holdout_contexts.jsonl
python -m experiments.evaluate isolate dev_samples.jsonl experiments/data/holdout_contexts.jsonl
```

Replace `dev_samples.jsonl` with the B module's development dataset. The candidate pool contains 60 classification examples and 40 delegation requests. Use the baseline command on candidates to check the workflow. Formal evaluation uses datasets frozen after reviewer checks. [Candidate datasets and reviewer workflow (Chinese)](data/README.md).

Measure resumption from `distraction_prompted` to the next meaningful main-task edit (`effective_edit`) under the same `run_id` and `goal_id`. The desktop integration for these events is pending. The analyzer reports missing start or end events and excludes incomplete pairs from timing statistics. Delegation delivery delay uses `delegation_completed` and `delegation_delivered`.

[Setup guide (Chinese)](../docs/GETTING_STARTED.md) · [Development and evaluation tasks](../TODO.en.md)
