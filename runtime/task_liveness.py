from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock


class LivenessError(ValueError):
    """Raised when a liveness record contains invalid input."""


@dataclass(frozen=True)
class TaskLiveness:
    """Immutable heartbeat snapshot for one active task execution."""

    task_id: str
    owner_id: str
    last_heartbeat_at: datetime
    last_progress_at: datetime

    def heartbeat_age(self, *, now: datetime | None = None) -> timedelta:
        return _utc_now(now) - self.last_heartbeat_at

    def progress_age(self, *, now: datetime | None = None) -> timedelta:
        return _utc_now(now) - self.last_progress_at

    def is_heartbeat_stale(self, *, now: datetime | None = None, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            raise LivenessError("timeout_seconds must be positive")
        return self.heartbeat_age(now=now) >= timedelta(seconds=float(timeout_seconds))


class TaskLivenessTracker:
    """Thread-safe heartbeat/progress registry independent of business task state."""

    def __init__(self) -> None:
        self._records: dict[str, TaskLiveness] = {}
        self._lock = RLock()

    def start(self, task_id: str, owner_id: str, *, now: datetime | None = None) -> TaskLiveness:
        _validate_identity(task_id, "task_id")
        _validate_identity(owner_id, "owner_id")
        timestamp = _utc_now(now)
        with self._lock:
            record = TaskLiveness(task_id, owner_id, timestamp, timestamp)
            self._records[task_id] = record
            return record

    def heartbeat(self, task_id: str, owner_id: str, *, now: datetime | None = None) -> TaskLiveness:
        timestamp = _utc_now(now)
        with self._lock:
            record = self._require_owner(task_id, owner_id)
            updated = TaskLiveness(record.task_id, record.owner_id, timestamp, record.last_progress_at)
            self._records[task_id] = updated
            return updated

    def progress(self, task_id: str, owner_id: str, *, now: datetime | None = None) -> TaskLiveness:
        timestamp = _utc_now(now)
        with self._lock:
            record = self._require_owner(task_id, owner_id)
            updated = TaskLiveness(record.task_id, record.owner_id, timestamp, timestamp)
            self._records[task_id] = updated
            return updated

    def get(self, task_id: str) -> TaskLiveness | None:
        _validate_identity(task_id, "task_id")
        with self._lock:
            return self._records.get(task_id)

    def stop(self, task_id: str, owner_id: str) -> None:
        with self._lock:
            self._require_owner(task_id, owner_id)
            del self._records[task_id]

    def _require_owner(self, task_id: str, owner_id: str) -> TaskLiveness:
        _validate_identity(task_id, "task_id")
        _validate_identity(owner_id, "owner_id")
        record = self._records.get(task_id)
        if record is None:
            raise LivenessError(f"No active liveness record for task {task_id}")
        if record.owner_id != owner_id:
            raise LivenessError(f"Worker {owner_id} does not own liveness for task {task_id}")
        return record


def _validate_identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LivenessError(f"{name} must be a non-empty string")


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise LivenessError("now must be timezone-aware")
    return value


__all__ = ["LivenessError", "TaskLiveness", "TaskLivenessTracker"]
