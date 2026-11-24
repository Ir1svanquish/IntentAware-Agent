"""Application flow shared by the GUI and tests; this module does not import Qt.

The caller owns the main thread. Providers run in the executor, while poll()
applies completed results and writes events on the calling/main thread.
"""

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

from intentaware.activity.models import task_title_key
from intentaware.contracts import (
    ActivityContext, ActivityLabel, Checkpoint, Classification, Condition,
    DelegationJob, DelegationResult, Detour, ExperimentEvent, Goal,
    JobStatus, Progress, Source, new_id, utc_now,
)
from intentaware.contracts.interfaces import Classifier, Delegator
from intentaware.delegation.demo import DemoDelegator
from intentaware.memory.store import SQLiteStore
from intentaware.memory.resume import recovery_key, recovery_text
from intentaware.nlp.local import LocalActivityClassifier


class DesktopSession:
    """One active goal, a run of events and replaceable classification/delegation."""

    def __init__(
        self,
        store: SQLiteStore,
        classifier: Classifier | None = None,
        delegator: Delegator | None = None,
        condition: Condition = Condition.D,
    ):
        self.store = store
        self.classifier = classifier if classifier is not None else LocalActivityClassifier()
        self.delegator = delegator if delegator is not None else DemoDelegator()
        self.condition = Condition(condition)
        self.run_id = new_id()
        self.goal = self.store.load_goal()
        self.progress = self.store.load_progress(self.goal.id) if self.goal else None
        self.goal_inference_key = None
        if self.goal:
            self.goal_inference_key = self.store.get_setting("goal_inference_key")
            if not self.goal_inference_key and self.store.get_setting("goal_origin") == "automatic":
                self.goal_inference_key = task_title_key(self.goal.title)
        self.jobs: list[DelegationJob] = []
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="intentaware")
        self._pending: dict[str, tuple[Future, Event]] = {}
        self._analysis_future: Future | None = None
        self._analysis_activity: str | None = None
        self.classification: Classification | None = None
        self.classification_activity: str | None = None
        self.analysis_error: str | None = None
        self._closed = False
        self._event("session_started", details=self._provider_details())

    def _provider_details(self) -> dict:
        return {"classifier": type(self.classifier).__name__, "delegator": type(self.delegator).__name__}

    @property
    def memory_enabled(self) -> bool:
        return self.condition != Condition.G

    @property
    def delegation_enabled(self) -> bool:
        return self.condition in (Condition.I, Condition.D)

    @property
    def analysis_pending(self) -> bool:
        return self._analysis_future is not None

    @property
    def detours(self) -> list[Detour]:
        return self.store.list_detours(self.goal.id) if self.goal else []

    @property
    def events(self) -> list[ExperimentEvent]:
        return self.store.list_events(self.run_id)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("当前工作台已关闭，请重新启动应用。")

    def _require_goal(self) -> Goal:
        self._require_open()
        if self.goal is None:
            raise ValueError("正在等待自动识别任务，也可点击“修正”设置当前任务。")
        return self.goal

    def _event(
        self, name: str, job: DelegationJob | None = None, details: dict | None = None,
        *, goal_id: str | None = None, run_id: str | None = None,
        condition: Condition | None = None,
    ) -> None:
        self.store.append_event(ExperimentEvent(
            run_id=run_id or self.run_id,
            condition=condition or (job.condition if job else self.condition),
            name=name,
            goal_id=goal_id or (job.goal_id if job else (self.goal.id if self.goal else None)),
            job_id=job.id if job else None,
            details=details or {},
        ))

    def record_event(self, name: str, details: dict | None = None) -> None:
        """Record non-content metadata on the owning/main thread."""
        self._require_open()
        self._event(name, details=details)

    def set_goal(self, title: str, next_step: str, progress_note: str = "", *, origin: str = "manual") -> Goal:
        return self._write_goal(title, next_step, progress_note, origin=origin, new=False)

    def start_goal(self, title: str, next_step: str, *, origin: str = "automatic") -> Goal:
        """Begin a distinct task without relabelling its predecessor's saved detours."""
        if any(job.status in (JobStatus.RUNNING, JobStatus.READY) for job in self.jobs):
            raise ValueError("请先查看或取消当前任务的委托，再切换到新任务。")
        return self._write_goal(title, next_step, "", origin=origin, new=True)

    def _write_goal(self, title: str, next_step: str, progress_note: str, *, origin: str, new: bool) -> Goal:
        self._require_open()
        if self.analysis_pending:
            raise ValueError("正在分析当前活动，请等待分析完成后再更新目标。")
        if not title.strip():
            raise ValueError("目标不能为空，请写下这次要完成的任务。")
        if origin not in ("manual", "automatic"):
            raise ValueError("任务来源无效。")
        goal = (
            replace(self.goal, title=title.strip(), next_step=next_step.strip())
            if self.goal and not new else Goal(title=title.strip(), next_step=next_step.strip())
        )
        progress = Progress(goal_id=goal.id, note=progress_note.strip())
        inference_key = task_title_key(goal.title) if new or origin == "automatic" else self.goal_inference_key
        with self.store.transaction():
            self.store.save_goal(goal)
            self.store.save_progress(progress)
            self.store.set_setting("goal_origin", origin)
            self.store.set_setting("goal_inference_key", inference_key)
            self._event("goal_saved", goal_id=goal.id, details={"origin": origin, "new_task": new})
        self.goal, self.progress = goal, progress
        self.goal_inference_key = inference_key
        self.classification = None
        self.classification_activity = None
        self.analysis_error = None
        if new:
            self.jobs.clear()
        return goal

    def set_condition(self, condition: Condition) -> None:
        self._require_open()
        condition = Condition(condition)
        if condition == self.condition:
            return
        if self.analysis_pending:
            raise ValueError("请等待当前活动分析完成后再切换实验条件。")
        if any(job.status in (JobStatus.RUNNING, JobStatus.READY) for job in self.jobs):
            raise ValueError("请先查看或取消尚未结束的委托，再切换实验条件。")
        run_id = new_id()
        with self.store.transaction():
            self._event("session_ended", details={"reason": "condition_changed"})
            self._event("session_started", details=self._provider_details(), run_id=run_id, condition=condition)
        self.condition = condition
        self.run_id = run_id
        self.jobs.clear()
        self.classification = None
        self.classification_activity = None
        self.analysis_error = None

    def _activity_context(self, activity: str) -> ActivityContext:
        goal = self._require_goal()
        if not activity.strip():
            raise ValueError("请先输入当前活动或粘贴上下文。")
        return ActivityContext(
            goal=goal,
            activity=activity.strip(),
            progress=self.progress.note if self.progress else "",
        )

    @staticmethod
    def _validate_classification(result: Classification) -> Classification:
        if not isinstance(result, Classification) or not isinstance(result.label, ActivityLabel):
            raise ValueError("分类模块返回了不符合约定的数据。")
        return result

    def _record_classification(self, result: Classification, activity: str) -> Classification:
        self._validate_classification(result)
        self._event("activity_classified", details={"label": result.label.value, "classifier": type(self.classifier).__name__})
        self.classification = result
        self.classification_activity = activity
        return result

    def analyze(self, activity: str) -> Classification:
        """Synchronous helper for scripts. The desktop uses start_analysis()."""
        context = self._activity_context(activity)
        return self._record_classification(self.classifier.classify(context), context.activity)

    def start_analysis(self, activity: str) -> None:
        context = self._activity_context(activity)
        if self.analysis_pending:
            raise ValueError("已有活动正在分析，请稍候。")
        self._event("analysis_requested")
        future = self._executor.submit(self.classifier.classify, context)
        self.classification = None
        self.classification_activity = None
        self.analysis_error = None
        self._analysis_future = future
        self._analysis_activity = context.activity

    def cancel_analysis(self) -> None:
        """Discard a stale result; a running provider may finish but cannot apply it."""
        self._require_open()
        if self._analysis_future is not None:
            self._analysis_future.cancel()
        self._analysis_future = None
        self._analysis_activity = None
        self.classification = None
        self.classification_activity = None
        self.analysis_error = None

    def add_detour(self, text: str, url: str = "", purpose: str = "") -> Detour:
        goal = self._require_goal()
        if not self.memory_enabled:
            raise ValueError("G 条件仅启用目标与活动分析，请切换到 P、I 或 D 记录偏离。")
        if not text.strip():
            raise ValueError("请输入要暂存的内容。")
        detour = Detour(goal_id=goal.id, text=text.strip(), url=url.strip(), purpose=purpose.strip())
        with self.store.transaction():
            self.store.add_detour(detour)
            self._event("detour_saved", details={"detour_id": detour.id})
        return detour

    def update_detour(self, detour_id: str, text: str, url: str = "", purpose: str = "") -> Detour:
        self._require_goal()
        if not self.memory_enabled:
            raise ValueError("当前实验条件未启用支线记忆。")
        original = next((item for item in self.detours if item.id == detour_id), None)
        if original is None:
            raise ValueError("找不到当前任务的这条支线记录。")
        updated = replace(original, text=text.strip(), url=url.strip(), purpose=purpose.strip())
        with self.store.transaction():
            self.store.update_detour(updated)
            self._event("detour_updated", details={"detour_id": detour_id})
        return updated

    def remove_detour(self, detour_id: str) -> None:
        self._require_goal()
        if not self.memory_enabled:
            raise ValueError("当前实验条件未启用偏离记录。")
        if not any(item.id == detour_id for item in self.detours):
            raise ValueError("找不到这条偏离记录，请重新选择。")
        with self.store.transaction():
            self.store.remove_detour(detour_id)
            self._event("detour_removed", details={"detour_id": detour_id})

    @property
    def recovery_paused(self) -> bool:
        return bool(self.store.get_setting("recovery_paused", False))

    def set_recovery_paused(self, paused: bool) -> None:
        self._require_goal()
        if not self.memory_enabled:
            raise ValueError("当前实验条件未启用恢复提示。")
        with self.store.transaction():
            self.store.set_setting("recovery_paused", bool(paused))
            self._event("recovery_paused" if paused else "recovery_resumed")

    def ignore_recovery(self) -> None:
        goal = self._require_goal()
        if not self.memory_enabled:
            raise ValueError("当前实验条件未启用恢复提示。")
        with self.store.transaction():
            self.store.set_setting(f"recovery_ignored:{goal.id}", recovery_key(goal, self.progress))
            self._event("recovery_ignored")

    def recovery_preview(self) -> str:
        if not self.memory_enabled:
            return "当前 G 条件未启用任务恢复。"
        if self.goal is None:
            return "请先在工作台设置主任务，再查看恢复提示。"
        if self.recovery_paused:
            return "恢复提示已暂停，仍可点击“恢复主任务”手动查看。"
        ignored = self.store.get_setting(f"recovery_ignored:{self.goal.id}")
        if ignored == recovery_key(self.goal, self.progress):
            return "本条恢复提示已忽略；更新任务或进度后将提供新的提示，也可手动查看。"
        return recovery_text(self.goal, self.progress, self.detours)

    def resume(self) -> str:
        goal = self._require_goal()
        if not self.memory_enabled:
            raise ValueError("当前实验条件未启用任务恢复。")
        text = recovery_text(goal, self.progress, self.detours)
        # A button click is a request, not evidence of a meaningful main-task edit.
        with self.store.transaction():
            self.store.set_setting(f"recovery_ignored:{goal.id}", None)
            self._event("resume_requested")
        return text

    def submit_delegation(self, question: str) -> DelegationJob:
        goal = self._require_goal()
        if not self.delegation_enabled:
            raise ValueError("异步委托仅在 I、D 条件下启用。")
        if not question.strip():
            raise ValueError("请输入需要委托的问题。")
        job = DelegationJob(goal_id=goal.id, question=question.strip(), condition=self.condition)
        cancel = Event()
        self._event("delegation_submitted", job)
        future = self._executor.submit(self.delegator.run, job.question, cancel)
        self.jobs.append(job)
        self._pending[job.id] = (future, cancel)
        return job

    def poll(self) -> bool:
        """Called by the Qt timer. Never call this from a worker thread."""
        if self._closed:
            return False
        changed = False
        if self._analysis_future is not None and self._analysis_future.done():
            try:
                result = self._validate_classification(self._analysis_future.result())
            except Exception as exc:
                self._event("analysis_failed", details={"error_type": type(exc).__name__})
                self.analysis_error = str(exc) or type(exc).__name__
            else:
                self._record_classification(result, self._analysis_activity or "")
                self.analysis_error = None
            # Keep the completed future available if a storage write raised.
            self._analysis_future = None
            self._analysis_activity = None
            changed = True
        for job_id, (future, cancel) in list(self._pending.items()):
            if not future.done():
                continue
            job = self._find_job(job_id)
            if job.status == JobStatus.CANCELLED:
                self._pending.pop(job_id)
                continue
            if cancel.is_set():
                self.cancel_job(job_id)
                changed = True
                continue
            changed = True
            try:
                result = future.result()
                if not isinstance(result, DelegationResult) or not result.answer.strip():
                    raise ValueError("委托模块没有返回有效的答案。")
                if len(result.sources) > 2:
                    raise ValueError("委托结果最多包含两份来源。")
                if not all(
                    isinstance(source, Source)
                    and isinstance(source.title, str) and source.title.strip()
                    and isinstance(source.url, str) and source.url.strip()
                    for source in result.sources
                ):
                    raise ValueError("来源必须使用 Source(title, url) 格式，且标题和链接不能为空。")
            except CancelledError:
                self.cancel_job(job.id)
                continue
            except Exception as exc:
                self._event("delegation_failed", job, {"error_type": type(exc).__name__})
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
                job.error = str(exc) or type(exc).__name__
                self._pending.pop(job_id)
                continue
            completed_at = utc_now()
            immediate = job.condition == Condition.I
            with self.store.transaction():
                self._event("delegation_completed", job)
                if immediate:
                    self._event("delegation_delivered", job, {"method": "immediate"})
            job.result = result
            job.status = JobStatus.DELIVERED if immediate else JobStatus.READY
            job.completed_at = completed_at
            job.delivered_at = completed_at if immediate else None
            self._pending.pop(job_id)
        return changed

    def _find_job(self, job_id: str) -> DelegationJob:
        for job in self.jobs:
            if job.id == job_id:
                return job
        raise ValueError("找不到这项委托，请重新选择。")

    def _deliver(self, job: DelegationJob, method: str) -> None:
        self._event("delegation_delivered", job, {"method": method})
        job.status = JobStatus.DELIVERED
        job.delivered_at = utc_now()

    def checkpoint(self) -> int:
        goal = self._require_goal()
        if not self.delegation_enabled:
            raise ValueError("当前实验条件未启用委托检查点。")
        self.poll()
        checkpoint = Checkpoint(goal_id=goal.id)
        ready = [job for job in self.jobs if job.status == JobStatus.READY]
        with self.store.transaction():
            self._event("checkpoint_reached", details={"checkpoint_id": checkpoint.id})
            for job in ready:
                self._event("delegation_delivered", job, {"method": "checkpoint"})
        for job in ready:
            job.status = JobStatus.DELIVERED
            job.delivered_at = utc_now()
        return len(ready)

    def reveal_job(self, job_id: str) -> DelegationJob:
        self._require_open()
        if not self.delegation_enabled:
            raise ValueError("当前实验条件未启用委托查看。")
        job = self._find_job(job_id)
        if job.status == JobStatus.DELIVERED:
            return job
        if job.status != JobStatus.READY:
            raise ValueError("答案尚未就绪，或这项委托已经取消、失败。")
        self._deliver(job, "early_view")
        return job

    def cancel_job(self, job_id: str) -> None:
        self._require_open()
        job = self._find_job(job_id)
        if job.status not in (JobStatus.RUNNING, JobStatus.READY):
            return
        self._event("delegation_cancelled", job)
        pending = self._pending.pop(job_id, None)
        if pending:
            future, cancel = pending
            cancel.set()
            future.cancel()
        job.status = JobStatus.CANCELLED
        job.result = None
        job.completed_at = job.completed_at or utc_now()

    def export_events(self, path: str | Path) -> int:
        self._require_open()
        return self.store.export_events(path, self.run_id)

    def close(self) -> None:
        if self._closed:
            return
        try:
            for job in self.jobs:
                if job.status in (JobStatus.RUNNING, JobStatus.READY):
                    self.cancel_job(job.id)
            self._event("session_ended", details={"reason": "window_closed"})
        finally:
            self._closed = True
            if self._analysis_future is not None:
                self._analysis_future.cancel()
                self._analysis_future = None
            for future, cancel in self._pending.values():
                cancel.set()
                future.cancel()
            self._pending.clear()
            self._executor.shutdown(wait=False, cancel_futures=True)
            self.store.close()
