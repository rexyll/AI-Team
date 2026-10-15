from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterator, TypeVar
from uuid import uuid4

from runtime.task_lease import LeaseOwnershipError, LeaseUnavailable
from runtime.task_lease_fencing import FencedLease, FencedTaskLeaseManager

T = TypeVar("T")


@dataclass(frozen=True)
class ExecutionLease:
    """Ownership handle held for one workflow execution attempt."""

    lease: FencedLease

    @property
    def task_id(self) -> str:
        return self.lease.lease.task_id

    @property
    def owner_id(self) -> str:
        return self.lease.lease.owner_id

    @property
    def token(self) -> str:
        return self.lease.lease.token

    @property
    def generation(self) -> int:
        return self.lease.generation


class WorkflowExecutionLease:
    """Coordinates workflow entry so a shared manager permits one worker per task."""

    def __init__(self, lease_manager: FencedTaskLeaseManager, *, owner_id: str | None = None) -> None:
        if not isinstance(lease_manager, FencedTaskLeaseManager):
            raise TypeError("lease_manager must be a FencedTaskLeaseManager")
        if owner_id is not None and (not isinstance(owner_id, str) or not owner_id.strip()):
            raise ValueError("owner_id must be a non-empty string or None")
        self.lease_manager = lease_manager
        self.owner_id = owner_id or f"worker-{uuid4().hex}"

    def acquire(self, task_id: str, *, ttl_seconds: float | None = None, now: datetime | None = None) -> ExecutionLease:
        return ExecutionLease(
            self.lease_manager.acquire(
                task_id,
                self.owner_id,
                ttl_seconds=ttl_seconds,
                now=now,
            )
        )

    def release(self, execution_lease: ExecutionLease) -> None:
        if not isinstance(execution_lease, ExecutionLease):
            raise TypeError("execution_lease must be an ExecutionLease")
        self.lease_manager.release(
            execution_lease.task_id,
            execution_lease.owner_id,
            execution_lease.token,
            execution_lease.generation,
        )

    def assert_current(self, execution_lease: ExecutionLease, *, now: datetime | None = None) -> None:
        if not isinstance(execution_lease, ExecutionLease):
            raise TypeError("execution_lease must be an ExecutionLease")
        self.lease_manager.assert_current(
            execution_lease.task_id,
            execution_lease.owner_id,
            execution_lease.token,
            execution_lease.generation,
            now=now,
        )

    @contextmanager
    def hold(self, task_id: str, *, ttl_seconds: float | None = None, now: datetime | None = None) -> Iterator[ExecutionLease]:
        execution_lease = self.acquire(task_id, ttl_seconds=ttl_seconds, now=now)
        try:
            yield execution_lease
        finally:
            try:
                self.release(execution_lease)
            except LeaseOwnershipError:
                # The lease may have expired or been fenced by a successor.
                # Never let cleanup of a stale worker mask the execution result.
                pass

    def run(self, task_id: str, action: Callable[[ExecutionLease], T], *, ttl_seconds: float | None = None, now: datetime | None = None) -> T:
        if not callable(action):
            raise TypeError("action must be callable")
        with self.hold(task_id, ttl_seconds=ttl_seconds, now=now) as execution_lease:
            self.assert_current(execution_lease, now=now)
            return action(execution_lease)


__all__ = [
    "ExecutionLease",
    "WorkflowExecutionLease",
    "LeaseUnavailable",
    "LeaseOwnershipError",
]
