from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock


@dataclass(frozen=True)
class TaskLease:
    task_id: str
    worker_id: str
    lease_id: str
    expires_at: float


class TaskLeaseCoordinator:
    """In-process reference implementation of worker ownership/lease semantics."""

    def __init__(self, *, clock=None) -> None:
        self._clock = clock or __import__("time").monotonic
        self._leases: dict[str, TaskLease] = {}
        self._lock = RLock()

    def acquire(self, task_id: str, worker_id: str, lease_id: str, ttl_s: float) -> TaskLease | None:
        if not task_id or not worker_id or not lease_id or ttl_s <= 0:
            raise ValueError("task_id, worker_id, lease_id and positive ttl_s are required")
        now = self._clock()
        with self._lock:
            current = self._leases.get(task_id)
            if current is not None and current.expires_at > now:
                return None
            lease = TaskLease(task_id, worker_id, lease_id, now + ttl_s)
            self._leases[task_id] = lease
            return lease

    def renew(self, task_id: str, worker_id: str, lease_id: str, ttl_s: float) -> TaskLease | None:
        if ttl_s <= 0:
            raise ValueError("positive ttl_s is required")
        now = self._clock()
        with self._lock:
            current = self._leases.get(task_id)
            if current is None or current.worker_id != worker_id or current.lease_id != lease_id or current.expires_at <= now:
                return None
            lease = TaskLease(task_id, worker_id, lease_id, now + ttl_s)
            self._leases[task_id] = lease
            return lease

    def release(self, task_id: str, worker_id: str, lease_id: str) -> bool:
        with self._lock:
            current = self._leases.get(task_id)
            if current is None or current.worker_id != worker_id or current.lease_id != lease_id:
                return False
            del self._leases[task_id]
            return True

    def owner(self, task_id: str) -> TaskLease | None:
        now = self._clock()
        with self._lock:
            current = self._leases.get(task_id)
            if current is None or current.expires_at <= now:
                if current is not None:
                    del self._leases[task_id]
                return None
            return current
