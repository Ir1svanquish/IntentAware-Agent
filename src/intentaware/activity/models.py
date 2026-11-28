"""Small immutable values shared by capture, recognition and the workbench."""

from dataclasses import dataclass, field
from hashlib import sha256
import json

from intentaware.contracts import utc_now


def task_title_key(title: str) -> str:
    """Identify an inferred task across several windows without retaining its old title."""
    normalized = " ".join(title.split()).casefold()
    return sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ActivitySnapshot:
    app_name: str
    window_title: str
    process_id: int | None = None
    source: str = "window_title"
    observed_at: str = field(default_factory=utc_now)

    @property
    def key(self) -> str:
        """A deterministic content key, independent of sampling time or PID."""
        content = json.dumps(
            [self.app_name.strip().casefold(), self.window_title.strip()],
            ensure_ascii=False, separators=(",", ":"),
        )
        return sha256(content.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class CaptureResult:
    snapshot: ActivitySnapshot | None
    status: str = "ok"
    message: str = ""


@dataclass(frozen=True)
class TaskSuggestion:
    title: str
    next_step: str
    activity: str
    confidence: str
    reason: str
    source_key: str
    category: str = "未知"
    identity_title: str = ""

    @property
    def task_key(self) -> str:
        return task_title_key(self.identity_title or self.title)
