from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class ProjectResult:
    """Provider-independent summary of one project execution.

    ``completed_task_ids`` is the canonical identity-level representation of
    completed tasks used by project persistence and recovery.
    """

    project: str | None
    success: bool
    status: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: tuple[str, ...]
    blocked_tasks: tuple[str, ...]
    completed_task_ids: tuple[str, ...] = ()

    @classmethod
    def from_task_manager(
        cls,
        task_manager: TaskManager,
        *,
        project: str | None = None,
    ) -> "ProjectResult":
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")

        tasks = task_manager.get_all_tasks()

        completed_task_ids = tuple(
            task.id
            for task in tasks
            if task.status == "completed"
        )

        failed = tuple(
            task.id
            for task in tasks
            if task.status == "failed"
        )

        blocked = tuple(
            task.id
            for task in tasks
            if task.status == "blocked"
        )

        completed = len(completed_task_ids)

        success = bool(tasks) and completed == len(tasks)

        if success:
            status = "completed"
        elif failed or blocked:
            status = "failed"
        else:
            status = "incomplete"

        return cls(
            project=project,
            success=success,
            status=status,
            total_tasks=len(tasks),
            completed_tasks=completed,
            failed_tasks=failed,
            blocked_tasks=blocked,
            completed_task_ids=completed_task_ids,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectResult":
        """Restore a ProjectResult from a persisted JSON-compatible payload."""

        if not isinstance(payload, dict):
            raise TypeError("project result payload must be a dictionary")

        project = payload.get("project")

        if project is not None and not isinstance(project, str):
            raise ValueError("project must be a string or None")

        success = payload.get("success")
        if not isinstance(success, bool):
            raise ValueError("success must be a boolean")

        status = payload.get("status")
        if not isinstance(status, str):
            raise ValueError("status must be a string")

        total_tasks = payload.get("total_tasks")
        if not isinstance(total_tasks, int) or isinstance(total_tasks, bool):
            raise ValueError("total_tasks must be an integer")

        completed_tasks = payload.get("completed_tasks")
        if not isinstance(completed_tasks, int) or isinstance(completed_tasks, bool):
            raise ValueError("completed_tasks must be an integer")

        failed_tasks = payload.get("failed_tasks", [])
        blocked_tasks = payload.get("blocked_tasks", [])
        completed_task_ids = payload.get("completed_task_ids", [])

        if not isinstance(failed_tasks, list):
            raise ValueError("failed_tasks must be a list")

        if not isinstance(blocked_tasks, list):
            raise ValueError("blocked_tasks must be a list")

        if not isinstance(completed_task_ids, list):
            raise ValueError("completed_task_ids must be a list")

        if not all(isinstance(item, str) for item in failed_tasks):
            raise ValueError("failed_tasks must contain strings")

        if not all(isinstance(item, str) for item in blocked_tasks):
            raise ValueError("blocked_tasks must contain strings")

        if not all(isinstance(item, str) for item in completed_task_ids):
            raise ValueError("completed_task_ids must contain strings")

        return cls(
            project=project,
            success=success,
            status=status,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=tuple(failed_tasks),
            blocked_tasks=tuple(blocked_tasks),
            completed_task_ids=tuple(completed_task_ids),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly, provider-independent representation."""

        return {
            "project": self.project,
            "success": self.success,
            "status": self.status,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": list(self.failed_tasks),
            "blocked_tasks": list(self.blocked_tasks),
            "completed_task_ids": list(self.completed_task_ids),
        }