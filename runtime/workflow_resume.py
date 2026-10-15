from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from runtime.task import Task
from runtime.workflow_resume_guard import ResumeDecision, WorkflowResumeGuard


class WorkflowResumeError(RuntimeError):
    """Raised when a recovered workflow cannot be resumed safely."""


@dataclass(frozen=True)
class ResumePlan:
    decisions: tuple[ResumeDecision, ...]

    @property
    def resumable_task_ids(self) -> tuple[str, ...]:
        return tuple(d.task_id for d in self.decisions if d.resumable)


class WorkflowResumePlanner:
    """Build an idempotent resume plan without mutating recovered tasks."""

    def __init__(self, guard: WorkflowResumeGuard | None = None) -> None:
        self._guard = guard or WorkflowResumeGuard()

    def plan(self, tasks: Iterable[Task]) -> ResumePlan:
        if tasks is None:
            raise WorkflowResumeError("tasks are required")
        seen: set[str] = set()
        decisions: list[ResumeDecision] = []
        for task in tasks:
            if not isinstance(task, Task):
                raise WorkflowResumeError("tasks must contain Task values")
            if task.id in seen:
                raise WorkflowResumeError(f"duplicate task id: {task.id}")
            seen.add(task.id)
            decisions.append(self._guard.decide(task))
        return ResumePlan(tuple(decisions))
