from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Callable

from runtime.task_lease import LeaseOwnershipError, TaskLease, TaskLeaseManager


@dataclass(frozen=True)
class FencedLease:
    lease: TaskLease
    generation: int


class FencedTaskLeaseManager:
    """Lease manager with monotonically increasing fencing generations."""

    def __init__(self, lease_manager: TaskLeaseManager | None = None, *, default_ttl_seconds: float = 60.0) -> None:
        if lease_manager is not None and not isinstance(lease_manager, TaskLeaseManager):
            raise TypeError("lease_manager must be a TaskLeaseManager or None")
        self._leases = lease_manager or TaskLeaseManager(default_ttl_seconds=default_ttl_seconds)
        self._generations: dict[str, int] = {}
        self._lock = RLock()

    def acquire(self, task_id: str, owner_id: str, *, ttl_seconds: float | None = None, now: datetime | None = None) -> FencedLease:
        with self._lock:
            lease = self._leases.acquire(task_id, owner_id, ttl_seconds=ttl_seconds, now=now)
            generation = self._generations.get(task_id, 0) + 1
            self._generations[task_id] = generation
            return FencedLease(lease, generation)

    def renew(self, task_id: str, owner_id: str, token: str, *, ttl_seconds: float | None = None, now: datetime | None = None) -> FencedLease:
        with self._lock:
            lease = self._leases.renew(task_id, owner_id, token, ttl_seconds=ttl_seconds, now=now)
            return FencedLease(lease, self._generations[task_id])

    def release(self, task_id: str, owner_id: str, token: str, generation: int) -> None:
        with self._lock:
            self.assert_current(task_id, owner_id, token, generation)
            self._leases.release(task_id, owner_id, token)

    def get(self, task_id: str, *, now: datetime | None = None) -> FencedLease | None:
        """Return the current fenced lease, or None when no live lease exists."""
        with self._lock:
            lease = self._leases.get(task_id, now=now)
            if lease is None:
                return None
            return FencedLease(lease, self._generations[task_id])

    def assert_current(self, task_id: str, owner_id: str, token: str, generation: int, *, now: datetime | None = None) -> None:
        if generation != self._generations.get(task_id):
            raise LeaseOwnershipError(f"Worker {owner_id} has stale fencing generation for task {task_id}")
        lease = self._leases.get(task_id, now=now)
        if lease is None or lease.owner_id != owner_id or lease.token != token:
            raise LeaseOwnershipError(f"Worker {owner_id} does not own task {task_id}")

    def guarded(self, task_id: str, owner_id: str, token: str, generation: int, action: Callable[[], object], *, now: datetime | None = None) -> object:
        self.assert_current(task_id, owner_id, token, generation, now=now)
        return action()


__all__ = ["FencedLease", "FencedTaskLeaseManager"]
