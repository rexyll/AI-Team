from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4


class LeaseError(RuntimeError):
    """Base error for task lease ownership violations."""


class LeaseUnavailable(LeaseError):
    """Raised when a task is already owned by a live lease."""


class LeaseOwnershipError(LeaseError):
    """Raised when a worker presents an invalid or stale lease token."""


@dataclass(frozen=True)
class TaskLease:
    task_id: str
    owner_id: str
    token: str
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return now >= self.expires_at


class TaskLeaseManager:
    """Thread-safe task ownership boundary for concurrent workers.

    This first lease boundary intentionally does not mutate Task lifecycle state.
    Execution code can acquire ownership before touching a Task and must present
    the returned opaque token when releasing it.
    """

    def __init__(self, *, default_ttl_seconds: float = 60.0) -> None:
        if isinstance(default_ttl_seconds, bool) or default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be positive")
        self.default_ttl_seconds = float(default_ttl_seconds)
        self._leases: dict[str, TaskLease] = {}
        self._lock = RLock()

    def acquire(
        self,
        task_id: str,
        owner_id: str,
        *,
        ttl_seconds: float | None = None,
        now: datetime | None = None,
    ) -> TaskLease:
        self._validate_identity(task_id, "task_id")
        self._validate_identity(owner_id, "owner_id")
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        current_time = self._utc_now(now)
        with self._lock:
            existing = self._leases.get(task_id)
            if existing is not None and not existing.is_expired(now=current_time):
                raise LeaseUnavailable(f"Task {task_id} is leased by {existing.owner_id}")
            lease = TaskLease(
                task_id=task_id,
                owner_id=owner_id,
                token=uuid4().hex,
                expires_at=current_time + timedelta(seconds=float(ttl)),
            )
            self._leases[task_id] = lease
            return lease

    def release(self, task_id: str, owner_id: str, token: str) -> None:
        self._validate_identity(task_id, "task_id")
        self._validate_identity(owner_id, "owner_id")
        self._validate_identity(token, "token")
        with self._lock:
            lease = self._leases.get(task_id)
            if lease is None or lease.owner_id != owner_id or lease.token != token:
                raise LeaseOwnershipError(f"Worker {owner_id} does not own task {task_id}")
            del self._leases[task_id]

    def get(self, task_id: str, *, now: datetime | None = None) -> TaskLease | None:
        self._validate_identity(task_id, "task_id")
        current_time = self._utc_now(now)
        with self._lock:
            lease = self._leases.get(task_id)
            if lease is None:
                return None
            if lease.is_expired(now=current_time):
                del self._leases[task_id]
                return None
            return lease

    @staticmethod
    def _validate_identity(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")

    @staticmethod
    def _utc_now(now: datetime | None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return value
