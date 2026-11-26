Language / 语言：[简体中文](README.md) | **English**

# IntentAware-Agent

**HKU COMP7607 · Natural Language Processing · Group 14**

A desktop task workbench that uses the foreground application and window title to infer your current task and activity. Review the result and correct it when needed. Recognition runs locally and does not read page or document contents.

## Quick start

Python 3.11 or newer is required. Run these commands from the repository root.

**Windows (PowerShell)**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m intentaware
```

After installing Python, you can also double-click [start.bat](start.bat) to start automatic recognition. The first launch downloads dependencies. Later launches can run offline.

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m intentaware
```

After launching, switch to VS Code, Word, or a browser window with a descriptive page title, stay there for a few seconds, and return to the workbench. When no task is saved and the title provides enough information, the app fills in the current task. Activity and classification update as windows change, without repeated typing. An existing task is preserved; use **修正** (Correct) when information is missing or the inference needs adjustment. The default study condition is D.

[Operation, module integration, and tests (Chinese)](docs/GETTING_STARTED.md)

### Platforms and launch modes

| Environment | Automatic recognition |
| --- | --- |
| Windows | Reads the foreground app and window title through native system APIs |
| Linux X11 | Requires an available graphical session and the `xprop` command |
| macOS / Linux Wayland | Currently unsupported; the app explains the limitation and allows manual task and activity input |

| Command | Behavior |
| --- | --- |
| `python -m intentaware` | Automatic recognition; saved pause and excluded-app settings remain in effect |
| `python -m intentaware --demo` | Clearly labeled simulated observations; defaults to a separate `demo` data subdirectory |
| `python -m intentaware --manual` | Starts with recognition paused; it can be enabled from the UI |

Use the virtual-environment Python path shown above, or activate the environment first.

### What runs today

- A Chinese-language PySide6 workbench that shows the current task, ongoing activity, inference source, and reasons. Task correction and optional manual activity input are available when needed.
- A first task inferred from a stable, informative foreground window, with four-way activity classification using local rules. Use **切换到此任务** (Switch to this task) to adopt a suggestion or **暂不切换** (Keep current task) to dismiss it for the current task during this session.
- Pause, resume, and application exclusions, with settings stored locally. Low-information titles remain uncertain and require correction.
- SQLite storage for the current goal, confirmed progress, and detours. Those records are available after restarting the app.
- G/P/I/D feature gates, background delegation with immediate or deferred delivery, early viewing, cancellation, and JSONL export for the current run. Delegation jobs live for the current app session.
- The default title and keyword rules run locally without network access or an API key. Use `--classifier llm` to enable [model-based classification](docs/GETTING_STARTED.md#llm-分类可选). Delegation returns offline demonstration results.

### Desktop preview

![IntentAware desktop workbench running locally](docs/images/desktop-starter.png)

## Overview

**IntentAware-Agent** is a desktop task companion for studying, writing, and coding. By default it uses foreground application and title metadata to classify activities in relation to the main goal, while preserving detours and user-confirmed progress. `--classifier llm` optionally connects an OpenAI-compatible model for goal clarification and four-way classification (API key required, off by default; tests and the default flow stay offline). Public-source retrieval and asynchronous delegation of non-urgent questions remain in development; the current delegator supports offline checks of background execution and delivery.

### Project proposal

[Read the course proposal (PDF)](docs/group14-project-proposal.pdf)

The original proposal describes a browser extension. The current implementation is a standalone Python and PySide6 desktop app that infers tasks from the foreground application and window title.

### Typical workflow

1. **Start working:** Launch the app and continue in an editor or browser. A stable, informative window title can establish the first task.
2. **Review and correct:** Check the displayed source. Use **修正** (Correct) to edit the task and next step. Human corrections are preserved.
3. **Follow your activity:** The workbench updates the activity, classification, and reason automatically. A window change never confirms progress.
4. **Handle new tasks and detours:** Adopt a suggestion when you want to change the main task. Save a detour, or use offline delegation to try the background and delivery workflow.
5. **Resume work:** Continue from your confirmed progress and next step. The sidebar also provides recognition controls, exclusions, and experiment records.

## Module goals

This table includes planned capabilities. See “What runs today” above for the implemented scope.

| Module | Responsibilities |
| --- | --- |
| **Goal & Intent** | Clarify the main goal and next step; classify activities in context with explanations |
| **Detour & Resume** | Store links, notes, and confirmed progress; suggest concrete resumption actions |
| **Async Delegation** | Turn questions into editable requests; retrieve up to two public sources and draft cited answers |
| **Deferred Delivery** | Control when results appear; support checkpoints, early viewing, and cancellation |
| **Experiment & Evaluation** | Log task events, switch study conditions, and evaluate classification and task continuity |

## Tech stack

| Component | Technology |
| --- | --- |
| Desktop GUI | **Python + PySide6** |
| Foreground observation | Native Windows APIs / Linux X11 `xprop` |
| NLP inference | Local task-inference and classification rules, with an interface for an LLM adapter |
| Local persistence | SQLite |
| Background processing | Python worker / thread |
| Experiment analysis (planned) | pandas + scikit-learn |
| Automated tests | pytest |

The application uses modular Python components. Foreground observations are sampled in the background; the task monitor passes stable observations to local recognition and classification. Users can correct or supplement the result. Task state, confirmed progress, and preferences stay local, while background results are applied on the main thread.

## Research and evaluation

Four feature conditions are compared:

| Condition | Capabilities |
| --- | --- |
| **G** | Goal-aware reminders |
| **P** | G + detour capture and task resumption |
| **I** | P + asynchronous delegation, with results shown when ready |
| **D** | P + asynchronous delegation, with checkpoint-based delivery (early viewing allowed) |

The evaluation plan includes a pilot, a within-participant study with **12–18 adults**, **60 task-context examples**, and **40 held-out delegation requests**.

Key measures include macro-F1 and false-warning rates for activity classification, task completion and output quality, resumption time, source support, perceived burden, latency, and token usage. Resumption time ends at the next observable meaningful main-task edit.

## Four-week development plan

| Week | Main deliverables |
| --- | --- |
| **1** | Project foundation, PySide6 UI, shared schemas, SQLite and LLM adapters; begin study preparation |
| **2** | End-to-end Goal & Intent and Detour & Resume flow |
| **3** | Async Delegation, Deferred Delivery, study-condition switches, and integration tests |
| **4** | Pilot and evaluation, analysis, demo, and final report |

## Project layout

```text
src/intentaware/
├── ui/             # Chinese desktop workbench
├── activity/       # Foreground observation, stability sampling, and task monitor
├── nlp/            # Local task inference and activity classification
├── memory/         # Progress, detours, and resumption
├── delegation/     # Offline delegation provider
├── contracts/      # Shared schemas and interfaces
├── session.py      # Feature gates, background work, and delivery
└── __main__.py     # Command-line entry point

experiments/        # Study tasks, logs, and analysis
tests/              # Automated tests
docs/               # Technical documentation and workstream guides
TODO.md             # Development checklist
CONTRIBUTING.md     # Team workflow
```

## Team collaboration

Team members can claim an entire workstream or specific subtasks through GitHub Issues:

**[A Desktop UI](https://github.com/Ir1svanquish/IntentAware-Agent/issues/1)** · **[B NLP](https://github.com/Ir1svanquish/IntentAware-Agent/issues/2)** · **[C Task Memory](https://github.com/Ir1svanquish/IntentAware-Agent/issues/3)** · **[D Delegation](https://github.com/Ir1svanquish/IntentAware-Agent/issues/4)** · **[E Evaluation](https://github.com/Ir1svanquish/IntentAware-Agent/issues/5)** · **[F Contracts & Integration](https://github.com/Ir1svanquish/IntentAware-Agent/issues/6)**

[All open tasks](https://github.com/Ir1svanquish/IntentAware-Agent/issues) · [Claiming & acceptance guide](docs/WORKSTREAMS.md) · [Development TODO](TODO.en.md) · [Contributing guide](CONTRIBUTING.en.md)


### Join the development team

Group members can comment with their GitHub handle and preferred module in [Join Request Issue #7](https://github.com/Ir1svanquish/IntentAware-Agent/issues/7). Maintainers can invite verified teammates; contributors may also fork and open Pull Requests.

## Data and privacy

Automatic observation reads the foreground application name and window title. With the default local classifier, observations stay on the device. The app skips its own window and private windows or password managers covered by its rules. Add excluded applications in **设置** (Settings), or pause recognition at any time.

When `--classifier llm` is enabled, the app sends the current goal, next step, confirmed progress, activity source, and current activity to the configured model endpoint. The activity may contain the foreground application name and window title. The app does not capture screenshots, keystrokes, or clipboard data, or read page, file, or document contents.

Tasks, confirmed progress, detours, and preferences are stored in local SQLite. Automatically seeded and user-edited task titles are saved and may include file or page names. Raw ongoing window titles are not appended to event exports. Review exported records for sensitive information that you explicitly saved. See the [setup guide (Chinese)](docs/GETTING_STARTED.md#本地数据与测试) for data locations and overrides.

Title-based rules provide limited evidence. A classification does not establish that editing occurred or progress was made. Meaningful main-task edits still require separate observation in the study. When adding a model provider, read API keys from local environment variables and explicitly define the data sent to that provider.
