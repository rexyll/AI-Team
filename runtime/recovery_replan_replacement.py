from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.recovery_replan_acceptance import ReplanAcceptance
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


@dataclass(frozen=True)
class ReplanGraphReplacement:
    """A fully materialized task graph ready for an atomic owner-level swap.

    This object is deliberately separate from ``TaskManager`` mutation. It
    contains the exact Task instances that may become authoritative after the
    caller performs the final owner-level swap.
    """

    tasks: tuple[Task, ...]


def materialize_replacement(
    manager: TaskManager,
    acceptance: ReplanAcceptance,
) -> ReplanGraphReplacement:
    """Materialize a replacement graph without mutating the live manager.

    Existing terminal tasks that remain in the replacement plan retain their
    lifecycle/result/review/test/retry history. A completed task cannot simply
    disappear from a re-plan because doing so would silently discard durable
    workflow history. Existing failed/blocked tasks may be superseded only
    when the replacement plan explicitly contains their task id; their prior
    state is retained as history until the new workflow changes it through the
    normal TaskManager state machine.
    """
    if not isinstance(manager, TaskManager):
        raise TypeError("manager must be a TaskManager")
    if not isinstance(acceptance, ReplanAcceptance):
        raise TypeError("acceptance must be a ReplanAcceptance")

    active_tasks = [
        task.id
        for task in manager.get_all_tasks()
        if manager.is_active(task.id)
    ]
    if active_tasks:
        raise RuntimeError(
            "Cannot materialize re-plan while tasks are active: "
            + ", ".join(active_tasks)
        )

    plan_tasks = acceptance.result.plan["tasks"]
    existing = {task.id: task for task in manager.get_all_tasks()}
    plan_ids = {item["id"] for item in plan_tasks}

    missing_completed = [
        task.id
        for task in manager.get_all_tasks()
        if task.status == TaskStatus.COMPLETED.value and task.id not in plan_ids
    ]
    if missing_completed:
        raise ValueError(
            "Re-plan cannot discard completed task history: "
            + ", ".join(missing_completed)
        )

    materialized: list[Task] = []
    for item in plan_tasks:
        previous = existing.get(item["id"])
        if previous is None:
            materialized.append(
                Task(
                    id=item["id"],
                    title=item["title"],
                    description=item["description"],
                    role=item["role"],
                    dependencies=list(item["dependencies"]),
                )
            )
            continue

        if previous.status == TaskStatus.COMPLETED.value:
            task = Task.from_dict(previous.to_dict())
            task.title = item["title"]
            task.description = item["description"]
            task.role = item["role"]
            task.dependencies = list(item["dependencies"])
            materialized.append(task)
            continue

        materialized.append(
            Task(
                id=item["id"],
                title=item["title"],
                description=item["description"],
                role=item["role"],
                dependencies=list(item["dependencies"]),
            )
        )

    return ReplanGraphReplacement(tasks=tuple(materialized))
