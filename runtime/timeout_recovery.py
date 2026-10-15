from __future__ import annotations

from dataclasses import dataclass

from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.timeout import TimeoutExceeded


@dataclass(frozen=True)
class TimeoutRecoveryDecision:
    """Explicit policy decision for a timed-out task.

    Timeout itself never chooses or performs retry/recovery. The workflow
    owner must explicitly choose a policy. This object records that choice
    without mutating the Task.
    """

    task_id: str
    action: str
    reason: str

    ALLOWED_ACTIONS = frozenset({"none", "retry", "recover"})

    def __post_init__(self) -> None:
        if self.action not in self.ALLOWED_ACTIONS:
            raise ValueError(f"unsupported timeout recovery action: {self.action}")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")


def decide_timeout_recovery(
    task: Task,
    *,
    action: str = "none",
    reason: str = "timeout recovery policy",
) -> TimeoutRecoveryDecision:
    """Validate an explicit timeout recovery choice without applying it.

    A timeout must already have put the task into ``CANCELLED``. The policy
    layer may request ``retry`` or ``recover``, but applying either action is
    deliberately outside this function so that timeout cannot silently
    mutate retry counters or bypass the TaskManager state machine.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if task.status != TaskStatus.CANCELLED.value:
        raise ValueError("timeout recovery requires a cancelled task")
    if not task.cancellation_requested:
        raise ValueError("timeout recovery requires cancellation state")
    if task.error is not None:
        raise ValueError("cancelled timeout task must not carry an error")
    if task.retry_attempt < 0:
        raise ValueError("retry_attempt must be non-negative")
    if action == "retry" and task.retry_attempt >= task.max_retries:
        raise ValueError("explicit timeout retry exceeds retry budget")

    return TimeoutRecoveryDecision(task.id, action, reason)


def timeout_exception_is_control_plane(exc: BaseException) -> bool:
    """Return whether an exception represents timeout control flow."""
    return isinstance(exc, TimeoutExceeded)
