"""Nonblocking foreground sampling; state and SQLite writes stay on the caller thread."""

import os
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING

from intentaware.localization import tr
from intentaware.activity.models import ActivitySnapshot, CaptureResult, TaskSuggestion, task_title_key
from intentaware.activity.observer import create_observer, is_private_snapshot
from intentaware.nlp.local import LocalTaskRecognizer

if TYPE_CHECKING:
    from intentaware.session import DesktopSession


def _app_key(name: str) -> str:
    return name.strip().replace("\\", "/").rsplit("/", 1)[-1].casefold().removesuffix(".exe")


class TaskMonitor:
    """Keep the main task stable while its foreground activity changes.

    Providers receive no database connection. Captures and title recognition run
    in one worker. poll() is deliberately called by the same thread as session.poll().
    A generation counter discards work begun before a pause or exclusion change.
    """

    def __init__(
        self, session: "DesktopSession", observer=None, *, stable_seconds: float = 3.0,
        interval_seconds: float = 1.0, clock=time.monotonic, enabled: bool | None = None,
    ):
        self.session = session
        self.observer = observer if observer is not None else create_observer()
        self.recognizer = LocalTaskRecognizer()
        self._clock = clock
        self._stable_seconds = max(0.0, stable_seconds)
        self._interval_seconds = max(0.0, interval_seconds)
        self.enabled = (
            bool(session.store.get_setting("activity_monitor.enabled", True))
            if enabled is None else enabled
        )
        self.excluded_apps = self._normalize_apps(session.store.get_setting("activity_monitor.excluded_apps", []))
        self.goal_origin = session.store.get_setting("goal_origin", "restored" if session.goal else "automatic")
        self.state = "starting" if self.enabled else "paused"
        self.message = tr("切换到工作窗口，停留几秒后自动识别。") if self.enabled else tr("自动识别已暂停，可随时恢复。")
        self.snapshot: ActivitySnapshot | None = None
        self.suggestion: TaskSuggestion | None = None
        self.activity_text = ""
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intentaware-observer")
        self._future: Future | None = None
        self._future_generation = 0
        self._generation = 0
        self._closed = False
        self._last_started = float("-inf")
        self._candidate_key: str | None = None
        self._candidate_since = 0.0
        self._accepted_key: str | None = None
        self._recorded_key: str | None = None
        self._analyzed_context: tuple | None = None
        self._dismissed_suggestions: set[tuple[str, str]] = set()

    @staticmethod
    def _normalize_apps(names) -> list[str]:
        if isinstance(names, str):
            names = re.split(r"[,，;；\n]", names)
        if not isinstance(names, (list, tuple, set)):
            return []
        return sorted({_app_key(name) for name in names if isinstance(name, str) and _app_key(name)})[:100]

    def _capture(self, excluded_apps: tuple[str, ...]) -> tuple[CaptureResult, TaskSuggestion | None]:
        result = self.observer.capture()
        if not isinstance(result, CaptureResult):
            raise ValueError(tr("前台采集模块返回的数据无效。"))
        snapshot = result.snapshot
        if snapshot is not None and snapshot.process_id == os.getpid():
            return CaptureResult(None, "idle", tr("正在使用 IntentAware，显示最近一次识别的活动。")), None
        if snapshot is not None and is_private_snapshot(snapshot):
            return CaptureResult(None, "excluded", tr("当前窗口已跳过识别，不显示或保存相关活动。")), None
        if snapshot is not None and _app_key(snapshot.app_name) in excluded_apps:
            return CaptureResult(None, "excluded", tr("当前应用已加入排除列表。")), None
        suggestion = self.recognizer.infer(snapshot) if snapshot is not None and result.status == "ok" else None
        return result, suggestion

    def _state(self, state: str, message: str) -> bool:
        changed = state != self.state or message != self.message
        self.state, self.message = state, message
        return changed

    def _clear_activity(self) -> None:
        self.snapshot = None
        self.suggestion = None
        self.activity_text = ""
        self._candidate_key = None
        self._accepted_key = None
        self._analyzed_context = None
        self.session.cancel_analysis()

    def _consume(self, result: CaptureResult, suggestion: TaskSuggestion | None) -> bool:
        snapshot = result.snapshot
        if snapshot is not None and _app_key(snapshot.app_name) in self.excluded_apps:
            result = CaptureResult(None, "excluded", tr("当前应用已加入排除列表。"))
            snapshot, suggestion = None, None
        if snapshot is None or result.status != "ok":
            state = result.status if result.status in ("idle", "excluded", "unavailable") else "unavailable"
            if state == "idle":
                # Keep the last external activity visible while the workbench has focus.
                self._candidate_key = None
                return self._state("idle", result.message or tr("等待可读取的工作窗口，显示最近一次活动。"))
            changed = self.snapshot is not None or self.state != state
            if changed:
                self._clear_activity()
            return self._state(state, result.message or tr("暂时无法识别，可点击修正手动设置任务。")) or changed

        if self._accepted_key == snapshot.key:
            changed = self.snapshot is None or self.snapshot.key != snapshot.key or not self.activity_text
            self.snapshot, self.suggestion = snapshot, suggestion
            self.activity_text = suggestion.activity if suggestion is not None else ""
            self._candidate_key = snapshot.key
            return self._state("watching", tr("正在自动识别，任务可随时修正。")) or changed
        if self._candidate_key != snapshot.key:
            self._candidate_key = snapshot.key
            self._candidate_since = self._clock()
            self.snapshot = snapshot
            self.suggestion = None
            self.activity_text = ""
            self._analyzed_context = None
            self.session.classification = None
            self.session.classification_activity = None
            self._state("sampling", tr("正在观察当前窗口，短暂切换不会改变任务。"))
            if self._stable_seconds > 0:
                return True
        if self._clock() - self._candidate_since < self._stable_seconds:
            return False
        if suggestion is None:
            raise ValueError(tr("任务识别模块没有返回建议。"))

        # Logs contain only source digests and coarse labels, never raw window titles.
        if self._recorded_key != snapshot.key:
            self.session.record_event("activity_observed", {
                "source_key": snapshot.key, "source": snapshot.source,
                "confidence": suggestion.confidence, "category": suggestion.category,
            })
            self._recorded_key = snapshot.key
        if self.session.goal is None and suggestion.title and suggestion.confidence in ("high", "medium"):
            self.session.start_goal(
                suggestion.title, suggestion.next_step, inference_key=suggestion.task_key,
            )
            self.goal_origin = "automatic"
        self.snapshot, self.suggestion = snapshot, suggestion
        self.activity_text = suggestion.activity
        self._accepted_key = snapshot.key
        self._state("watching", tr("正在自动识别，任务可随时修正。") if suggestion.title else tr("窗口信息不足，可以点击修正补充任务。"))
        return True

    def _analysis_context(self) -> tuple | None:
        goal = self.session.goal
        if not goal or not self.activity_text:
            return None
        return (self.session.run_id, goal.id, goal.title, goal.next_step,
                self.session.progress.note if self.session.progress else "", self.activity_text)

    def _analyze_if_needed(self) -> bool:
        goal = self.session.goal
        if not self.enabled or not goal or not self.activity_text or self.state not in ("watching", "idle"):
            return False
        context = self._analysis_context()
        if self.session.analysis_pending or context == self._analyzed_context:
            return False
        self.session.start_analysis(self.activity_text)
        self._analyzed_context = context
        return True

    def analyze_manual(self, activity: str) -> None:
        """Keep an explicit activity analysis until the observed context changes."""
        self.session.start_analysis(activity)
        self._analyzed_context = self._analysis_context()

    def poll(self) -> bool:
        if self._closed:
            return False
        changed = False
        if self._future is not None and self._future.done():
            if self.enabled and self._future_generation == self._generation:
                try:
                    result, suggestion = self._future.result()
                except Exception:
                    self._clear_activity()
                    changed = self._state("error", tr("暂时未能读取当前窗口，稍后会自动重试。"))
                else:
                    # Leave a successful future in place if a SQLite write fails; retry next tick.
                    changed = self._consume(result, suggestion)
            self._future = None
        if self.enabled:
            changed = self._analyze_if_needed() or changed
            if self._future is None and self._clock() - self._last_started >= self._interval_seconds:
                self._last_started = self._clock()
                self._future_generation = self._generation
                self._future = self._executor.submit(self._capture, tuple(self.excluded_apps))
        return changed

    def pause(self) -> None:
        if self._closed:
            return
        with self.session.store.transaction():
            self.session.store.set_setting("activity_monitor.enabled", False)
            self.session.record_event("observation_paused")
        self.enabled = False
        self._generation += 1
        self._clear_activity()
        self._state("paused", tr("自动识别已暂停，当前任务已保留。"))

    def resume(self) -> None:
        if self._closed:
            return
        with self.session.store.transaction():
            self.session.store.set_setting("activity_monitor.enabled", True)
            self.session.record_event("observation_resumed")
        self.enabled = True
        self._generation += 1
        self._last_started = float("-inf")
        self._state("starting", tr("切换到工作窗口，停留几秒后自动识别。"))

    def correct_task(self, title: str, next_step: str, progress_note: str = ""):
        goal = self.session.set_goal(title, next_step, progress_note, origin="manual")
        self.goal_origin = "manual"
        self._analyzed_context = None
        return goal

    @property
    def switch_suggestion(self) -> TaskSuggestion | None:
        goal, suggestion = self.session.goal, self.suggestion
        if goal is None or suggestion is None or not suggestion.title:
            return None
        key = suggestion.task_key
        if key in (self.session.goal_inference_key, task_title_key(goal.title)):
            return None
        if (goal.id, key) in self._dismissed_suggestions:
            return None
        return suggestion

    def dismiss_suggestion(self) -> None:
        suggestion = self.switch_suggestion
        goal = self.session.goal
        if goal and suggestion:
            self._dismissed_suggestions.add((goal.id, suggestion.task_key))

    def adopt_suggestion(self):
        suggestion = self.switch_suggestion
        if suggestion is None:
            raise ValueError(tr("当前没有可切换的任务建议。"))
        goal = self.session.start_goal(
            suggestion.title, suggestion.next_step, origin="manual", inference_key=suggestion.task_key,
        )
        self.goal_origin = "manual"
        self._analyzed_context = None
        self._dismissed_suggestions.clear()
        return goal

    def set_excluded_apps(self, names) -> None:
        normalized = self._normalize_apps(names)
        self.session.store.set_setting("activity_monitor.excluded_apps", normalized)
        self.excluded_apps = normalized
        self._generation += 1
        self._last_started = float("-inf")
        if self.snapshot and _app_key(self.snapshot.app_name) in normalized:
            self._clear_activity()
            self._state("excluded", tr("当前应用已加入排除列表。"))

    def exclude_current_app(self) -> None:
        if self.snapshot is None:
            raise ValueError(tr("尚未识别到应用，请在排除列表中填写应用名称。"))
        self.set_excluded_apps([*self.excluded_apps, self.snapshot.app_name])

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        if self._future is not None:
            self._future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
