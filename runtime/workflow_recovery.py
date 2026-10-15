from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from runtime.task import Task
from runtime.task_recovery import TaskRecoveryError
from runtime.workflow_checkpoint import WorkflowCheckpoint, WorkflowCheckpointError


class WorkflowRecoveryError(ValueError):
    """Raised when workflow execution state cannot be safely resumed."""


RESUMABLE_STATUSES = frozenset({"ready", "running", "review_pending", "reviewing"})


@dataclass(frozen=True)
class WorkflowExecutionState:
    """Recovered task/dependency view used to decide what may resume."""

    tasks: tuple[Task, ...]
    completed_task_ids: frozenset[str]
    resumable_task_ids: frozenset[str]

    @classmethod
    def from_tasks(cls, tasks: Iterable[Task]) -> "WorkflowExecutionState":
        recovered = tuple(tasks)
        completed = frozenset(task.id for task in recovered if task.status == "completed")
        resumable = frozenset(task.id for task in recovered if task.status in RESUMABLE_STATUSES)
        return cls(tasks=recovered, completed_task_ids=completed, resumable_task_ids=resumable)

    def task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise WorkflowRecoveryError(f"recovered task not found: {task_id}")

    def can_resume(self, task_id: str) -> bool:
        return task_id in self.resumable_task_ids and task_id not in self.completed_task_ids


class WorkflowRecovery:
    """Restore workflow checkpoints and expose safe-resume decisions."""

    def recover_checkpoint(self, checkpoint: WorkflowCheckpoint) -> WorkflowExecutionState:
        if not isinstance(checkpoint, WorkflowCheckpoint):
            raise WorkflowRecoveryError("checkpoint must be a WorkflowCheckpoint")
        try:
            return WorkflowExecutionState.from_tasks((checkpoint.restore(),))
        except WorkflowCheckpointError as exc:
            raise WorkflowRecoveryError("invalid workflow checkpoint") from exc

    def recover_tasks(self, checkpoints: Iterable[WorkflowCheckpoint]) -> WorkflowExecutionState:
        if checkpoints is None:
            raise WorkflowRecoveryError("checkpoints are required")
        try:
            tasks = tuple(checkpoint.restore() for checkpoint in checkpoints)
        except WorkflowCheckpointError as exc:
            raise WorkflowRecoveryError("invalid workflow checkpoint") from exc
        except AttributeError as exc:
            raise WorkflowRecoveryError("checkpoints must contain WorkflowCheckpoint values") from exc
        ids = [task.id for task in tasks]
        if len(ids) != len(set(ids)):
            raise WorkflowRecoveryError("duplicate recovered task id")
        return WorkflowExecutionState.from_tasks(tasks)
