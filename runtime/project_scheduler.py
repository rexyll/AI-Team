from __future__ import annotations

from dataclasses import dataclass

from runtime.dependency_scheduler import DependencyScheduler
from runtime.resource_governor import ResourceGovernor
from runtime.task import Task


@dataclass(frozen=True)
class ProjectExecutionScope:
    """Immutable identity for one project's scheduling scope."""

    project_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        object.__setattr__(self, "project_id", self.project_id.strip())


@dataclass(frozen=True)
class ProjectAdmissionDecision:
    """Pure scheduling decision; it never mutates task lifecycle state."""

    scope: ProjectExecutionScope
    task_id: str
    admitted: bool
    reason: str | None = None


class ProjectScheduler:
    """Coordinate project-scoped admission using existing canonical scheduler primitives."""

    def __init__(
        self,
        scope: ProjectExecutionScope,
        tasks: list[Task],
        governor: ResourceGovernor,
    ) -> None:
        if not isinstance(scope, ProjectExecutionScope):
            raise TypeError("scope must be a ProjectExecutionScope")
        if not isinstance(tasks, list):
            raise TypeError("tasks must be a list")
        if not isinstance(governor, ResourceGovernor):
            raise TypeError("governor must be a ResourceGovernor")
        for task in tasks:
            if not isinstance(task, Task):
                raise TypeError("all tasks must be Task instances")
            task_project_id = task.context.get("project_id")
            if task_project_id is not None and task_project_id != scope.project_id:
                raise ValueError(
                    f"task {task.id} belongs to project {task_project_id!r}, not {scope.project_id!r}"
                )
        self._scope = scope
        self._scheduler = DependencyScheduler(tasks)
        self._governor = governor

    @property
    def scope(self) -> ProjectExecutionScope:
        return self._scope

    @property
    def governor(self) -> ResourceGovernor:
        return self._governor

    def admissible_tasks(self) -> tuple[Task, ...]:
        return tuple(self._scheduler.get_admissible_tasks(self._governor))

    def decide(self, task_id: str) -> ProjectAdmissionDecision:
        decision = self._scheduler.decision_for(task_id)
        if not decision.runnable:
            return ProjectAdmissionDecision(
                self._scope,
                task_id,
                False,
                decision.reason,
            )
        if not self._governor.can_start_task():
            return ProjectAdmissionDecision(
                self._scope,
                task_id,
                False,
                "concurrency resource limit exceeded",
            )
        return ProjectAdmissionDecision(self._scope, task_id, True, None)
