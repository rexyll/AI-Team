from __future__ import annotations

from dataclasses import dataclass

from runtime.recovery_replan_adapter import ReplanResult
from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class ReplanAcceptance:
    """Validated re-plan safe to hand off for later graph replacement.

    Acceptance is deliberately separate from mutation. A live TaskManager is
    not changed by this contract.
    """

    result: ReplanResult


def accept_replan(manager: TaskManager, result: ReplanResult) -> ReplanAcceptance:
    """Accept a candidate only when the current task graph is quiescent."""
    if not isinstance(manager, TaskManager):
        raise TypeError("manager must be a TaskManager")
    if not isinstance(result, ReplanResult):
        raise TypeError("result must be a ReplanResult")

    active_tasks = [
        task.id
        for task in manager.get_all_tasks()
        if manager.is_active(task.id)
    ]
    if active_tasks:
        raise RuntimeError(
            "Cannot accept re-plan while tasks are active: "
            + ", ".join(active_tasks)
        )

    return ReplanAcceptance(result=result)
