[Chinese](MVP_DEMO.md)

# IntentAware-Agent MVP demo

## Run the demo

From the repository root, install the app in a virtual environment and use a fresh demo data directory. The demo uses a simulated foreground window, local activity classification, and one preset documentation excerpt. After installation it runs offline.

```bash
python -m pip install .
python -m intentaware --lang en --demo --condition D --data-dir ./demo-mvp
```

On Windows, `.\start.bat --lang en --demo --condition D --data-dir demo-mvp` sets up the virtual environment and launches the same demo.

1. Wait for the workbench to infer an IntentAware-Agent task from the simulated editor window.
2. Open **Experiments & Logs → Load demo example**. Select **Save changes** to save the task, next step, and confirmed progress. Select **Analyze activity**, then **Save as detour** next to the assessment when it marks the activity as a possible detour.
3. Open **Delegation → Prepare request**, then select **Confirm and submit** for the prefilled question about `argparse`. Wait for **Ready to deliver**. Open **Detours & Recovery** to see the saved progress and next step, then select **Back to workbench**. The answer stays hidden.
4. Return to **Delegation** and choose **Reach checkpoint**. The answer reveals a checked excerpt and its source. Run with `--condition I` and a separate data directory to demonstrate immediate delivery with the same question and evidence.
5. In research use, once an observer sees a meaningful edit to the original task, choose **Experiments & Logs → Record main-task edit**. The workbench records the displayed detour prompt separately. Choose **Export JSONL** and save as `events-demo.jsonl`. The export is tagged as a demo run.

```bash
python -m experiments.evaluate check events-demo.jsonl
python -m experiments.evaluate events events-demo.jsonl
python -m experiments.evaluate baseline tests/fixtures/nlp_samples.jsonl
```

## One-minute talk track

**Motivation.** Related side questions can pull people away from their main task. IntentAware helps users save those detours and pick up where they left off.

**Methodology.** We classify activities into four relevance categories. Our evaluation design compares four conditions, from goal-aware reminders through detour recovery to immediate and checkpoint-based delivery. The last two use the same delegation pipeline.

**Implementation.** We built a PySide6 desktop app with foreground-window observation, editable goals, SQLite task memory and an asynchronous worker. The demo uses a preset source and shows how the app checks the excerpt and holds the result until a checkpoint.

**Key results.** On 40 development examples, the keyword baseline reached 87.5% accuracy and 0.876 macro-F1. One DeepSeek run reached 90.0% and 0.896. The desktop demo also verified task recovery, deferred delivery and a valid event export. Held-out evaluation and the participant study are pending.

## Evidence and scope

- [Classification run, configuration and error analysis (Chinese)](../src/intentaware/nlp/README.md#真实模型基线2026-11-24). Both scores use the same development set of 40 examples. The DeepSeek figures are from the recorded run. The baseline is reproducible with the command above.
- [Desktop integration test](../tests/test_automatic_ui.py) covers inference, correction, detour capture, task restoration after reopening, deferred delivery and a matched prompt/edit in the JSONL export.
- The desktop app uses foreground application names and window titles. The [proposal](group14-project-proposal.pdf) described a browser-based design. Windows foreground capture and the external retrieval/model path can be tested separately from this offline demo. See the [live delegation setup (Chinese)](../src/intentaware/delegation/README.md) and [experiment protocol](../experiments/README.en.md).
