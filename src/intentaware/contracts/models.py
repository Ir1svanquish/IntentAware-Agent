"""跨模块数据结构。时间统一为带时区的 UTC ISO 8601 字符串。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid4().hex


class Condition(str, Enum):
    G = "G"
    P = "P"
    I = "I"
    D = "D"


class ActivityLabel(str, Enum):
    DIRECT_PROGRESS = "direct_progress"
    NECESSARY_PREPARATION = "necessary_preparation"
    OPTIONAL_EXPLORATION = "optional_exploration"
    UNCLEAR = "unclear"


class JobStatus(str, Enum):
    RUNNING = "running"
    READY = "ready"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Goal:
    title: str
    next_step: str
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class Progress:
    goal_id: str
    note: str
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ActivityContext:
    goal: Goal
    activity: str
    progress: str = ""


@dataclass(frozen=True)
class Classification:
    label: ActivityLabel
    reason: str
    suggested_next_step: str


@dataclass(frozen=True)
class Detour:
    goal_id: str
    text: str
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utc_now)
    url: str = ""
    purpose: str = ""


@dataclass(frozen=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True)
class DelegationResult:
    answer: str
    sources: tuple[Source, ...] = ()


@dataclass
class DelegationJob:
    goal_id: str
    question: str
    condition: Condition
    id: str = field(default_factory=new_id)
    status: JobStatus = JobStatus.RUNNING
    created_at: str = field(default_factory=utc_now)
    result: DelegationResult | None = None
    error: str | None = None
    completed_at: str | None = None
    delivered_at: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    goal_id: str
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ExperimentEvent:
    run_id: str
    condition: Condition
    name: str
    goal_id: str | None = None
    job_id: str | None = None
    details: dict = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    occurred_at: str = field(default_factory=utc_now)
