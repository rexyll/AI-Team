from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from runtime.task import Task
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_recovery import RESUMABLE_STATUSES, WorkflowRecovery


class RecoveryTriggerError(ValueError):
    """Raised when a recovery-trigger decision cannot be evaluated safely."""


class RecoveryTriggerState(str, Enum):
    NOT_STUCK = "not_stuck"
    WAITING_FOR_LEASE_EXPIRY = "waiting_for_lease_expiry"
    NOT_RESUMABLE = "not_resumable"
    TRIGGERED = "triggered"


@dataclass(frozen=True)
class RecoveryTriggerDecision:
    task_id: str
    state: RecoveryTriggerState
    reason: str

    @property
    def should_recover(self) -> bool:
        return self.state is RecoveryTriggerState.TRIGGERED


class WorkflowRecoveryTrigger:
    """Turn a stuck assessment into a safe, side-effect-free recovery decision."""

    def __init__(self, lease_manager: FencedTaskLeaseManager, recovery: WorkflowRecovery | None = None) -> None:
        if lease_manager is None:
            raise ValueError("lease_manager is required")
        if not isinstance(lease_manager, FencedTaskLeaseManager):
            raise TypeError("lease_manager must be a FencedTaskLeaseManager")
        self._leases = lease_manager
        self._recovery = recovery or WorkflowRecovery()

    def evaluate(
        self,
        task: Task,
        assessment: StuckTaskAssessment,
        *,
        now: datetime | None = None,
    ) -> RecoveryTriggerDecision:
        if not isinstance(task, Task):
            raise RecoveryTriggerError("task must be a Task")
        if not isinstance(assessment, StuckTaskAssessment):
            raise RecoveryTriggerError("assessment must be a StuckTaskAssessment")
        if task.id != assessment.task_id:
            raise RecoveryTriggerError("assessment task id does not match task")

        if assessment.state is not TaskLivenessState.STUCK:
            return RecoveryTriggerDecision(task.id, RecoveryTriggerState.NOT_STUCK, "task is not classified as stuck")
        if task.status not in RESUMABLE_STATUSES:
            return RecoveryTriggerDecision(task.id, RecoveryTriggerState.NOT_RESUMABLE, "task status is not resumable")
        if self._leases.get(task.id, now=now) is not None:
            return RecoveryTriggerDecision(task.id, RecoveryTriggerState.WAITING_FOR_LEASE_EXPIRY, "active execution lease still exists")
        return RecoveryTriggerDecision(task.id, RecoveryTriggerState.TRIGGERED, "stuck task has no active execution lease")


__all__ = ["RecoveryTriggerError", "RecoveryTriggerState", "RecoveryTriggerDecision", "WorkflowRecoveryTrigger"]
