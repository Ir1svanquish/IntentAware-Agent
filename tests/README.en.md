Language: [Chinese](README.md) | **English**

# Tests

Install the development dependencies, then run this command from the repository root:

```bash
python -m pytest
```

Tests use temporary databases and controlled foreground observations or system interfaces. They do not call a live model or access the internet. Native-adapter tests do not replace checks on Windows or Linux X11 desktops.

| File | Coverage |
| --- | --- |
| `test_observer.py` | Windows native handles, X11 title parsing, privacy filters, timeouts, and unsupported environments |
| `test_task_inference.py` | Chinese and English title inference, sparse titles, task relevance, and local classification |
| `test_monitor.py` | Stable sampling, initial tasks, correction, task switching, pause, exclusions, and saved preferences |
| `test_automatic_ui.py` | Automatic display, correction drafts, task suggestions, pause, exclusions, and shutdown |
| `test_classifier.py` | Original demo classifier categories, rule priority, and context |
| `test_storage.py` | Persistence, updates, deletion, restarts, and export |
| `test_session.py` | Background analysis and delegation, G/P/I/D gates, condition changes, delivery, and failures |
| `test_ui.py` | Qt interactions, responsiveness, results, and layout |

For headless Linux:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest
```

Manually check normal launch, `--demo`, and `--manual`. Automatic mode should display a task or an explicit uncertain state after a stable observation. Correcting a task and then switching applications must preserve the main task and must not create confirmed progress. Delayed activity results must not reappear after pause or exclusion.

[Setup and development guide (Chinese)](../docs/GETTING_STARTED.md)
