Language: [Chinese](README.md) | **English**

# PySide6 desktop source

After installing from the repository root, run `python -m intentaware --lang en` to open the workbench in English. To save a language preference, go to **Settings → Interface language** and restart the app. Normal launch observes the foreground application and window title, then applies local task-inference and classification rules. `--demo` uses simulated observations; `--manual` starts with recognition paused. Delegation remains an offline demonstration.

| Entry point | Responsibility |
| --- | --- |
| A [Desktop UI](ui/README.md) | `ui/window.py` and `ui/theme.py`: current task, automatic activity, correction, detours, delegation, and experiment pages. |
| B [Task and activity classification](nlp/README.md) | `nlp/local.py`: `LocalTaskRecognizer` infers task suggestions and `LocalActivityClassifier` provides four-way classification. `nlp/demo.py` retains the original demo classifier. |
| C [Task memory](memory/README.md) | `memory/store.py`: SQLite storage for tasks, confirmed progress, detours, events, and observation preferences. |
| D [Asynchronous delegation](delegation/README.md) | `delegation/demo.py`: offline background delegation for completion, delivery, and cancellation checks. |
| E [Evaluation](../../experiments/) | Uses JSONL events from each G/P/I/D run, with separate observation of meaningful main-task edits. |
| F [Foreground observation](activity/README.md) and [shared contracts](contracts/README.md) | `activity/` handles platform adapters, stable sampling, and the task monitor. `contracts/`, `session.py`, and `__main__.py` define shared values, coordinate the session, and assemble the app. |

Observation uses native Windows APIs or Linux X11 `xprop`. Automatic observation is not supported on macOS or Wayland. Raw ongoing window titles are omitted from event exports, while inferred task titles are saved as local tasks. Observations never populate confirmed progress.

Reusing a data directory restores tasks, progress, detours, and pause/exclusion preferences. Delegation jobs are actionable only in the current study run; running jobs are not resumed after restarting.

[Run, extend, and test the app (Chinese)](../../docs/GETTING_STARTED.md) · [Home](../../README.en.md) · [Claim work](../../docs/WORKSTREAMS.md)
