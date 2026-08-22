from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class ProjectResult:
    """Provider-independent summary of one project execution.

    ``completed_task_ids`` was added as a persistence/recovery invariant.
    It is intentionally backward-compatible with the original result
    contract: callers that do not provide it continue to work, and legacy
    serialized results without the field remain loadable.
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

        completed_ids = tuple(
            task.id
            for task in tasks
            if task.status == "completed"
        )

        completed = len(completed_ids)

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
            completed_task_ids=completed_ids,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectResult":
        """Restore a ProjectResult from its JSON representation.

        The loader accepts both the current representation and legacy
        representations that do not contain ``completed_task_ids``.
        """
        if not isinstance(payload, dict):
            raise TypeError("project result payload must be a dictionary")

        required = (
            "project",
            "success",
            "status",
            "total_tasks",
            "completed_tasks",
            "failed_tasks",
            "blocked_tasks",
        )

        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(
                f"project result payload is missing fields: {', '.join(missing)}"
            )

        project = payload["project"]
        success = payload["success"]
        status = payload["status"]
        total_tasks = payload["total_tasks"]
        completed_tasks = payload["completed_tasks"]
        failed_tasks = payload["failed_tasks"]
        blocked_tasks = payload["blocked_tasks"]

        if project is not None and not isinstance(project, str):
            raise ValueError("project must be a string or None")

        if not isinstance(success, bool):
            raise ValueError("success must be a boolean")

        if not isinstance(status, str):
            raise ValueError("status must be a string")

        if not isinstance(total_tasks, int) or isinstance(total_tasks, bool):
            raise ValueError("total_tasks must be an integer")

        if not isinstance(completed_tasks, int) or isinstance(completed_tasks, bool):
            raise ValueError("completed_tasks must be an integer")

        if not isinstance(failed_tasks, list):
            raise ValueError("failed_tasks must be a list")

        if not isinstance(blocked_tasks, list):
            raise ValueError("blocked_tasks must be a list")

        if any(not isinstance(task_id, str) for task_id in failed_tasks):
            raise ValueError("failed_tasks must contain only strings")

        if any(not isinstance(task_id, str) for task_id in blocked_tasks):
            raise ValueError("blocked_tasks must contain only strings")

        # Legacy snapshots did not contain completed_task_ids.
        #
        # In that case we cannot reconstruct the exact completed IDs from
        # ProjectResult alone. Keep the field empty rather than inventing IDs.
        completed_task_ids_payload = payload.get("completed_task_ids", [])

        if not isinstance(completed_task_ids_payload, list):
            raise ValueError("completed_task_ids must be a list")

        if any(
            not isinstance(task_id, str)
            for task_id in completed_task_ids_payload
        ):
            raise ValueError("completed_task_ids must contain only strings")

        return cls(
            project=project,
            success=success,
            status=status,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=tuple(failed_tasks),
            blocked_tasks=tuple(blocked_tasks),
            completed_task_ids=tuple(completed_task_ids_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation.

        Preserve the original serialized contract when no completed task IDs
        are available. New results produced from a TaskManager carry the
        additional identity information required by persistence/recovery.
        """
        payload: dict[str, Any] = {
            "project": self.project,
            "success": self.success,
            "status": self.status,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": list(self.failed_tasks),
            "blocked_tasks": list(self.blocked_tasks),
        }

        if self.completed_task_ids:
            payload["completed_task_ids"] = list(self.completed_task_ids)

        return payload