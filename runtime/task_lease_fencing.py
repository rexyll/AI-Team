from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from runtime.task_lease import LeaseOwnershipError, TaskLease, TaskLeaseManager


@dataclass(frozen=True)
class FencedLease:
    lease: TaskLease
    generation: int


class FencedTaskLeaseManager:
    """Lease manager with monotonically increasing fencing generations."""

    def __init__(self, *, default_ttl_seconds: float = 60.0) -> None:
        self._leases = TaskLeaseManager(default_ttl_seconds=default_ttl_seconds)
        self._generations: dict[str, int] = {}

    def acquire(self, task_id: str, owner_id: str, *, ttl_seconds: float | None = None, now: datetime | None = None) -> FencedLease:
        lease = self._leases.acquire(task_id, owner_id, ttl_seconds=ttl_seconds, now=now)
        generation = self._generations.get(task_id, 0) + 1
        self._generations[task_id] = generation
        return FencedLease(lease, generation)

    def renew(self, task_id: str, owner_id: str, token: str, *, ttl_seconds: float | None = None, now: datetime | None = None) -> FencedLease:
        lease = self._leases.renew(task_id, owner_id, token, ttl_seconds=ttl_seconds, now=now)
        return FencedLease(lease, self._generations[task_id])

    def release(self, task_id: str, owner_id: str, token: str, generation: int) -> None:
        self.assert_current(task_id, owner_id, token, generation)
        self._leases.release(task_id, owner_id, token)

    def assert_current(self, task_id: str, owner_id: str, token: str, generation: int, *, now: datetime | None = None) -> None:
        if generation != self._generations.get(task_id):
            raise LeaseOwnershipError(f"Worker {owner_id} has stale fencing generation for task {task_id}")
        lease = self._leases.get(task_id, now=now)
        if lease is None or lease.owner_id != owner_id or lease.token != token:
            raise LeaseOwnershipError(f"Worker {owner_id} does not own task {task_id}")

    def guarded(self, task_id: str, owner_id: str, token: str, generation: int, action: Callable[[], object], *, now: datetime | None = None) -> object:
        self.assert_current(task_id, owner_id, token, generation, now=now)
        return action()
