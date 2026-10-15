from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from runtime.task import Task
from runtime.task_status import TaskStatus


class RecoveryAction(str, Enum):
    NOOP = "noop"
    REQUEUE = "requeue"
    RESTORE = "restore"
    MANUAL = "manual"


@dataclass(frozen=True)
class CrashRecoveryDecision:
    """Deterministic recovery decision for a task after worker loss."""

    task_id: str
    previous_status: str
    action: RecoveryAction
    reason: str
    resource_reconciliation_required: bool


_INTERRUPTED_STATUSES = frozenset(
    {
        TaskStatus.RUNNING.value,
        TaskStatus.REVIEW_PENDING.value,
        TaskStatus.REVIEWING.value,
        TaskStatus.REVISION.value,
    }
)

_TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)


def decide_crash_recovery(task: Task) -> CrashRecoveryDecision:
    """Return a conservative recovery action without mutating ``task``.

    A worker crash is not a task failure. Persisted work that was in an
    execution/review state is considered interrupted and may be requeued by
    an explicit recovery coordinator. Terminal states are never replayed.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")

    status = task.status
    if status in _TERMINAL_STATUSES:
        return CrashRecoveryDecision(
            task.id,
            status,
            RecoveryAction.NOOP,
            "terminal task state is not replayed",
            False,
        )

    if status in _INTERRUPTED_STATUSES:
        return CrashRecoveryDecision(
            task.id,
            status,
            RecoveryAction.REQUEUE,
            "worker interruption requires explicit task requeue",
            True,
        )

    if status in {
        TaskStatus.PENDING.value,
        TaskStatus.READY.value,
        TaskStatus.BLOCKED.value,
    }:
        return CrashRecoveryDecision(
            task.id,
            status,
            RecoveryAction.RESTORE,
            "persisted non-running task can be restored without replay",
            False,
        )

    return CrashRecoveryDecision(
        task.id,
        status,
        RecoveryAction.MANUAL,
        "unknown task state requires manual recovery",
        True,
    )


def recoverable_after_crash(task: Task) -> bool:
    """Return whether a task has an explicit automatic recovery path."""
    decision = decide_crash_recovery(task)
    return decision.action in {
        RecoveryAction.REQUEUE,
        RecoveryAction.RESTORE,
    }


def recovery_snapshot(task: Task) -> dict[str, Any]:
    """Build a persistence-safe recovery record without changing the task."""
    decision = decide_crash_recovery(task)
    return {
        "task_id": decision.task_id,
        "previous_status": decision.previous_status,
        "action": decision.action.value,
        "reason": decision.reason,
        "resource_reconciliation_required": decision.resource_reconciliation_required,
        "retry_attempt": task.retry_attempt,
        "max_retries": task.max_retries,
        "cancellation_requested": task.cancellation_requested,
        "cancellation_reason": task.cancellation_reason,
    }
