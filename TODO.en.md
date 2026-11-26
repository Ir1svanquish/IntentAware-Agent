Language / 语言：[简体中文](TODO.md) | **English**

# Four-week Sprint Checklist

> The desktop workbench observes foreground windows, infers tasks with local rules, and supports human correction. The evaluation tools and candidate datasets are available. Optional LLM classification and goal clarification are available, with local rules as the default. The LLM achieved a macro-F1 of 0.896 on 40 development examples. Validation on the held-out dataset, live retrieval, and the formal study remain pending. Claim modules in [GitHub Issues](https://github.com/Ir1svanquish/IntentAware-Agent/issues).

## Week 1 — Foundation and early study preparation

- [ ] [Team] Claim five roles and an F contract coordinator (may overlap)
- [x] [F] Define Goal, ActivityContext, Classification, Progress, Detour, DelegationJob, Checkpoint and ExperimentEvent contracts
- [x] [A/F] Build the PySide6 workbench around the current task, activity, and reasons, with correction and optional manual input
- [x] [A/B/F] Implement native Windows foreground observation and Linux X11 observation through `xprop`; state macOS/Wayland limits
- [x] [A/C/F] Add stable sampling, pause/resume, application exclusions, and locally saved settings
- [x] [C/F] Set up SQLite storage for goals, progress, detours and events
- [x] [F] Provide replaceable classifier/delegator interfaces and offline demo implementations
- [x] [B] Connect a real LLM API and versioned prompts
- [ ] [E] Begin controlled study task/log design, recruitment and consent/ethics preparation

## Week 2 — Core MVP

- [x] [B/F] Seed the first task from a stable, informative window title; update activity and classify it with local rules
- [x] [A/B/F] Support human correction and one-click adoption of task suggestions; preserve the main task through temporary app switches
- [x] [C] Store detours and confirmed progress locally, with basic resumption suggestions
- [x] [B] Improve goal clarification, next-action extraction, four-way classification, and reasons using NLP/LLMs, and evaluate classification on 40 development examples
- [ ] [C] Evaluate and improve resumption strategies based on confirmed progress
- [ ] [A+B+C] Manually verify observation → correction → classification → detour → resumption on supported platforms
- [x] [E] Prepare 60 classification candidates and 40 delegation candidates, and check the classification candidates against the 40 development examples for exact overlap
- [ ] [E] Have two reviewers independently label the classification candidates, check semantic overlap, and freeze the held-out datasets

## Week 3 — Delegation and pilot

- [ ] [D] Editable delegation draft with at most one clarification
- [ ] [D] In-app background retrieval of at most two public sources; verify citations and unresolved points
- [x] [D+A] Offline delegation supports I immediate delivery, D manual checkpoints, early viewing, and cancellation
- [ ] [D+A] Recheck delivery, timeouts, failures, and cancellation after connecting live retrieval
- [x] [E/F] G/P/I/D condition switches, current-run events, and JSONL export
- [ ] [E/F] Complete integration checks across all four conditions after connecting NLP/LLMs and live retrieval
- [ ] [Team] Pilot and major fixes

## Week 4 — Evaluation and submission

- [ ] [E+Team] Evaluate 60 task-context examples (two reviewers) and 40 held-out requests as proposed
- [x] [E] Implement the keyword baseline, macro-F1, false-warning rate, delegation delay, and resumption-time analysis
- [ ] [E] Report classification metrics, output quality, source support, latency, and token usage on formal study data
- [ ] [Team] Subject to approvals/consent, conduct planned 12–18-person study; honestly report unfinished tasks
- [ ] [A/F/E] Record the side-question prompt and the next meaningful edit of the same task, then verify both events in desktop JSONL exports
- [ ] [Team] Demo, tests, analysis and final report

## Starter entry points

- [Getting started and module integration (Chinese)](docs/GETTING_STARTED.md): installation, demo, module replacement and tests.
- [Evaluation tools](experiments/README.en.md) and [candidate datasets (Chinese)](experiments/data/README.md).
- `src/intentaware/session.py`: connects the UI, NLP, persistence and background delegation.
- `src/intentaware/activity/`: foreground observation, stable sampling, and the task monitor; `src/intentaware/nlp/local.py`: local task inference and activity classification.
- Normal launch enables recognition; `--demo` uses simulated window observations; `--manual` starts with recognition paused.
- Default inference uses application names, titles, and local rules. Use `--classifier llm` to select an OpenAI-compatible model for activity classification. Delegation returns offline examples while live retrieval is pending.
- Preserve G/P/I/D. Window observations do not confirm progress or meaningful edits, and raw ongoing window titles are excluded from event exports.

## Definition of done

Reproducible code/docs, setup steps, happy/error tests, and review by another teammate. [Workstream guide (Chinese)](docs/WORKSTREAMS.md).
