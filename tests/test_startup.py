"""Exercise the real desktop startup in separate processes."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest


_STARTUP = """
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from intentaware.__main__ import main
from intentaware.ui.window import MainWindow

ready, release, *args = sys.argv[1:]
show_window = MainWindow.show

def show(self):
    show_window(self)
    if not ready:
        QTimer.singleShot(0, self.close)
        return
    Path(ready).touch()

    def close_on_release():
        if Path(release).exists():
            self.close()
        else:
            QTimer.singleShot(50, close_on_release)

    close_on_release()

def print_dialog(parent, title, text):
    print(text, flush=True)
    return QMessageBox.StandardButton.Ok

MainWindow.show = show
QMessageBox.warning = print_dialog
QMessageBox.critical = print_dialog
sys.exit(main(args))
"""


@pytest.mark.parametrize("shutdown", ["normal", "forced"])
def test_desktop_rejects_concurrent_use_of_the_same_data_directory(tmp_path, shutdown):
    source = Path(__file__).resolve().parents[1] / "src"
    env = {**os.environ, "PYTHONPATH": str(source), "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    shared = tmp_path / "shared"
    ready = tmp_path / "ready"
    release = tmp_path / "release"

    def command(path, *, holding=False, language="en"):
        return [
            sys.executable, "-c", _STARTUP, str(ready) if holding else "",
            str(release) if holding else "", "--manual", "--lang", language, "--data-dir", str(path),
        ]

    first = subprocess.Popen(command(shared, holding=True), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "The first desktop window did not start"
        another = subprocess.run(command(tmp_path / "separate"), env=env, capture_output=True, timeout=15)
        assert another.returncode == 0, another.stderr

        for path, language, message in ((shared, "en", "already open"), (shared / ".." / shared.name, "zh", "已在另一个")):
            duplicate = subprocess.run(command(path, language=language), env=env, capture_output=True, timeout=15)
            assert duplicate.returncode == 1, duplicate
            assert message in duplicate.stdout.decode("utf-8")
        with closing(sqlite3.connect(shared / "intentaware.sqlite3")) as database:
            started = database.execute("SELECT COUNT(*) FROM events WHERE payload LIKE '%session_started%'").fetchone()[0]
        assert started == 1

        if shutdown == "forced":
            first.kill()
        else:
            release.touch()
        first.wait(timeout=10)
        if shutdown == "normal":
            assert first.returncode == 0

        reopened = subprocess.run(command(shared), env=env, capture_output=True, timeout=15)
        assert reopened.returncode == 0, reopened
    finally:
        if first.poll() is None:
            first.kill()
        first.communicate(timeout=10)
