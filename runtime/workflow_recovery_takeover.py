from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from runtime.task import Task
from runtime.task_lease import LeaseUnavailable
from runtime.task_lease_fencing import FencedLease, FencedTaskLeaseManager
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_recovery import WorkflowRecovery
from runtime.workflow_recovery_trigger import (
    RecoveryTriggerDecision,
    RecoveryTriggerState,
    WorkflowRecoveryTrigger,
)


class RecoveryTakeoverError(RuntimeError):
    """Raised when a recovery takeover cannot be completed safely."""


@dataclass(frozen=True)
class RecoveryTakeover:
    task: Task
    lease: FencedLease
    decision: RecoveryTriggerDecision


class WorkflowRecoveryTakeover:
    """Atomically re-acquire execution ownership before resuming a stuck checkpoint."""

    def __init__(self, lease_manager: FencedTaskLeaseManager, recovery: WorkflowRecovery | None = None) -> None:
        if not isinstance(lease_manager, FencedTaskLeaseManager):
            raise TypeError("lease_manager must be a FencedTaskLeaseManager")
        self._leases = lease_manager
        self._recovery = recovery or WorkflowRecovery()
        self._trigger = WorkflowRecoveryTrigger(lease_manager, self._recovery)

    def takeover(
        self,
        checkpoint: WorkflowCheckpoint,
        assessment,
        *,
        owner_id: str,
        now: datetime | None = None,
        ttl_seconds: float | None = None,
    ) -> RecoveryTakeover:
        if not isinstance(checkpoint, WorkflowCheckpoint):
            raise RecoveryTakeoverError("checkpoint must be a WorkflowCheckpoint")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise RecoveryTakeoverError("owner_id must be a non-empty string")
        task = checkpoint.restore()
        decision = self._trigger.evaluate(task, assessment, now=now)
        if decision.state is not RecoveryTriggerState.TRIGGERED:
            raise RecoveryTakeoverError(f"recovery takeover rejected: {decision.state.value}")
        try:
            lease = self._leases.acquire(task.id, owner_id, ttl_seconds=ttl_seconds, now=now)
        except LeaseUnavailable as exc:
            # A competing worker may have acquired the lease after evaluation.
            raise RecoveryTakeoverError("recovery takeover lost the ownership race") from exc
        return RecoveryTakeover(task=task, lease=lease, decision=decision)


__all__ = ["RecoveryTakeoverError", "RecoveryTakeover", "WorkflowRecoveryTakeover"]
