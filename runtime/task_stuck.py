from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from runtime.task_liveness import LivenessError, TaskLiveness


class StuckTaskError(ValueError):
    """Raised for invalid stuck-task classification input."""


class TaskLivenessState(str, Enum):
    HEALTHY = "healthy"
    HEARTBEAT_STALE = "heartbeat_stale"
    NO_PROGRESS = "no_progress"
    STUCK = "stuck"


@dataclass(frozen=True)
class StuckTaskPolicy:
    heartbeat_timeout_seconds: float
    progress_timeout_seconds: float

    def __post_init__(self) -> None:
        if self.heartbeat_timeout_seconds <= 0 or self.progress_timeout_seconds <= 0:
            raise StuckTaskError("timeouts must be positive")


@dataclass(frozen=True)
class StuckTaskAssessment:
    task_id: str
    owner_id: str
    state: TaskLivenessState
    heartbeat_age: timedelta
    progress_age: timedelta

    @property
    def is_stuck(self) -> bool:
        return self.state is TaskLivenessState.STUCK


class StuckTaskClassifier:
    """Classify execution liveness without mutating task business state."""

    def __init__(self, policy: StuckTaskPolicy) -> None:
        self.policy = policy

    def classify(self, record: TaskLiveness, *, now: datetime | None = None) -> StuckTaskAssessment:
        if not isinstance(record, TaskLiveness):
            raise StuckTaskError("record must be a TaskLiveness")
        try:
            heartbeat_age = record.heartbeat_age(now=now)
            progress_age = record.progress_age(now=now)
            heartbeat_stale = record.is_heartbeat_stale(
                now=now, timeout_seconds=self.policy.heartbeat_timeout_seconds
            )
        except LivenessError as exc:
            raise StuckTaskError(str(exc)) from exc
        progress_stale = progress_age >= timedelta(seconds=self.policy.progress_timeout_seconds)
        if heartbeat_stale and progress_stale:
            state = TaskLivenessState.STUCK
        elif heartbeat_stale:
            state = TaskLivenessState.HEARTBEAT_STALE
        elif progress_stale:
            state = TaskLivenessState.NO_PROGRESS
        else:
            state = TaskLivenessState.HEALTHY
        return StuckTaskAssessment(record.task_id, record.owner_id, state, heartbeat_age, progress_age)


__all__ = ["StuckTaskError", "TaskLivenessState", "StuckTaskPolicy", "StuckTaskAssessment", "StuckTaskClassifier"]
