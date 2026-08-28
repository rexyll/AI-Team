from __future__ import annotations

from dataclasses import dataclass

from runtime.resource_governor import ResourceGovernor
from runtime.task import Task


@dataclass(frozen=True)
class ResourceAdmissionDecision:
    """Read-only admission result; resource rejection is not task failure."""

    task_id: str
    admitted: bool
    reason: str | None = None


def admit_task(task: Task, governor: ResourceGovernor) -> ResourceAdmissionDecision:
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(governor, ResourceGovernor):
        raise TypeError("governor must be a ResourceGovernor")

    snapshot = governor.start_task()
    if snapshot is None:
        return ResourceAdmissionDecision(
            task_id=task.id,
            admitted=False,
            reason="Resource limit reached: max_concurrent_tasks",
        )
    return ResourceAdmissionDecision(task_id=task.id, admitted=True)
