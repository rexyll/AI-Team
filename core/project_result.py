from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class ProjectResult:
    """Provider-independent summary of one project execution."""

    project: str | None
    success: bool
    status: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: tuple[str, ...]
    blocked_tasks: tuple[str, ...]

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
        failed = tuple(
            task.id for task in tasks if task.status == "failed"
        )
        blocked = tuple(
            task.id for task in tasks if task.status == "blocked"
        )
        completed = sum(
            task.status == "completed" for task in tasks
        )

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
        }
