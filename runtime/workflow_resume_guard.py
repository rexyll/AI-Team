from __future__ import annotations

from dataclasses import dataclass

from runtime.task import Task
from runtime.workflow_recovery import RESUMABLE_STATUSES, WorkflowRecoveryError


class WorkflowResumeError(RuntimeError):
    """Raised when a recovered task is not safe to resume."""


@dataclass(frozen=True)
class ResumeDecision:
    task_id: str
    resumable: bool
    reason: str


class WorkflowResumeGuard:
    """Central policy for deciding whether recovered work may re-enter execution."""

    def decide(self, task: Task) -> ResumeDecision:
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        status = task.status
        if status == "completed":
            return ResumeDecision(task.id, False, "already_completed")
        if status in RESUMABLE_STATUSES:
            return ResumeDecision(task.id, True, "safe_to_resume")
        return ResumeDecision(task.id, False, f"status_not_resumable:{status}")

    def require_resumable(self, task: Task) -> Task:
        decision = self.decide(task)
        if not decision.resumable:
            raise WorkflowResumeError(
                f"task {decision.task_id} cannot be resumed: {decision.reason}"
            )
        return task

    def require_not_completed(self, task: Task) -> Task:
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        if task.status == "completed":
            raise WorkflowResumeError(f"task {task.id} is already completed")
        return task
