"""Backward-compatible ProjectResult import and constructor boundary.

The canonical result model lives in ``core.project_result``.  This runtime
module remains import-compatible with older callers that still construct the
result with the former ``summary``/``pending_tasks``/numeric-count shape, while
ensuring every instance is also a canonical ``core.project_result.ProjectResult``
for persistence and recovery.
"""

from __future__ import annotations

from typing import Any

from core.project_result import ProjectResult as _CoreProjectResult
from runtime.task_manager import TaskManager


class ProjectResult(_CoreProjectResult):
    """Compatibility subclass accepted by the canonical persistence layer.

    New code should prefer ``core.project_result.ProjectResult``.  The legacy
    constructor is intentionally retained here because external/runtime callers
    may still provide the historical fields.
    """

    def __init__(
        self,
        *,
        success: bool,
        project: str | None,
        summary: str | None = None,
        total_tasks: int,
        completed_tasks: int,
        failed_tasks: int | tuple[str, ...] | list[str] = (),
        pending_tasks: int = 0,
        tasks: list[Any] | None = None,
        status: str | None = None,
        blocked_tasks: tuple[str, ...] | list[str] = (),
        completed_task_ids: tuple[str, ...] | list[str] = (),
    ) -> None:
        del summary, tasks

        if isinstance(failed_tasks, int):
            failed_ids: tuple[str, ...] = ()
        else:
            failed_ids = tuple(failed_tasks)

        if isinstance(blocked_tasks, (tuple, list)):
            blocked_ids = tuple(blocked_tasks)
        else:
            blocked_ids = ()

        if not blocked_ids and pending_tasks > 0:
            blocked_ids = tuple()

        completed_ids = tuple(completed_task_ids)
        if not completed_ids and completed_tasks == total_tasks and total_tasks > 0:
            # The legacy constructor did not carry task identities.  Preserve
            # the canonical count without inventing ids.
            completed_ids = ()

        if status is None:
            if success:
                status = "completed"
            elif failed_ids or (isinstance(failed_tasks, int) and failed_tasks > 0):
                status = "failed"
            else:
                status = "incomplete"

        super().__init__(
            project=project,
            success=success,
            status=status,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=failed_ids,
            blocked_tasks=blocked_ids,
            completed_task_ids=completed_ids,
        )

    @classmethod
    def from_task_manager(
        cls,
        task_manager: TaskManager,
        *,
        project: str | None = None,
    ) -> "ProjectResult":
        canonical = _CoreProjectResult.from_task_manager(task_manager, project=project)
        return cls(
            project=canonical.project,
            success=canonical.success,
            status=canonical.status,
            total_tasks=canonical.total_tasks,
            completed_tasks=canonical.completed_tasks,
            failed_tasks=canonical.failed_tasks,
            blocked_tasks=canonical.blocked_tasks,
            completed_task_ids=canonical.completed_task_ids,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectResult":
        canonical = _CoreProjectResult.from_dict(payload)
        return cls(
            project=canonical.project,
            success=canonical.success,
            status=canonical.status,
            total_tasks=canonical.total_tasks,
            completed_tasks=canonical.completed_tasks,
            failed_tasks=canonical.failed_tasks,
            blocked_tasks=canonical.blocked_tasks,
            completed_task_ids=canonical.completed_task_ids,
        )


__all__ = ["ProjectResult"]
