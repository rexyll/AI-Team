from __future__ import annotations

from dataclasses import dataclass

from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.timeout import TimeoutController


@dataclass(frozen=True)
class TimeoutDecision:
    """Control-plane timeout outcome for one task."""

    task_id: str
    timed_out: bool
    cancelled: bool
    retryable: bool = False
    reason: str | None = None


class TimeoutExecutionController:
    """Integrate cooperative timeout with Task and resource lifecycle.

    Timeout is deliberately not represented as an ordinary task failure. A
    timed-out task is cancelled, and an admitted task's resource slot is
    released exactly once through the execution coordinator. Retry policy is
    returned as a decision and is never mutated implicitly here.
    """

    def __init__(self, resources: ResourceExecutionCoordinator) -> None:
        if not isinstance(resources, ResourceExecutionCoordinator):
            raise TypeError("resources must be a ResourceExecutionCoordinator")
        self._resources = resources

    @property
    def resources(self) -> ResourceExecutionCoordinator:
        return self._resources

    def check(self, task: Task, timeout: TimeoutController) -> TimeoutDecision:
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        if not isinstance(timeout, TimeoutController):
            raise TypeError("timeout must be a TimeoutController")

        if not timeout.check():
            return TimeoutDecision(task.id, False, task.cancellation_requested)

        if task.status != TaskStatus.CANCELLED.value:
            task.cancel("task timeout exceeded")
        if self._resources.is_active(task.id):
            self._resources.cancel(task.id)
        return TimeoutDecision(
            task.id,
            True,
            task.cancellation_requested,
            False,
            task.cancellation_reason,
        )

    def enforce(self, task: Task, timeout: TimeoutController) -> TimeoutDecision:
        decision = self.check(task, timeout)
        if decision.timed_out:
            timeout.raise_if_expired()
        return decision