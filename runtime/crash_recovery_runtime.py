from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from runtime.crash_recovery import CrashRecoveryDecision, RecoveryAction, decide_crash_recovery
from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.task import Task
from runtime.task_persistence import TaskPersistenceAdapter


@dataclass(frozen=True)
class CrashRecoveryReport:
    """Result of reconciling persisted tasks after a worker crash."""

    decisions: tuple[CrashRecoveryDecision, ...]
    released_task_ids: tuple[str, ...]
    recoverable_task_ids: tuple[str, ...]
    terminal_task_ids: tuple[str, ...]


class CrashRecoveryCoordinator:
    """Reconcile persisted Task state with in-memory execution resources.

    Recovery is intentionally conservative: persistence is read-only during
    reconciliation, terminal tasks are never replayed, and active resource
    slots belonging to interrupted tasks are released exactly once. Requeue
    remains an explicit action for a higher-level scheduler.
    """

    def __init__(
        self,
        persistence: TaskPersistenceAdapter,
        resources: ResourceExecutionCoordinator,
    ) -> None:
        if not isinstance(persistence, TaskPersistenceAdapter):
            raise TypeError("persistence must be a TaskPersistenceAdapter")
        if not isinstance(resources, ResourceExecutionCoordinator):
            raise TypeError("resources must be a ResourceExecutionCoordinator")
        self._persistence = persistence
        self._resources = resources

    def inspect(self, task_ids: Iterable[str] | None = None) -> CrashRecoveryReport:
        ids = self._persistence.list_ids() if task_ids is None else list(task_ids)
        tasks = tuple(self._persistence.load(task_id) for task_id in ids)
        decisions = tuple(decide_crash_recovery(task) for task in tasks)

        released: list[str] = []
        recoverable: list[str] = []
        terminal: list[str] = []

        for task, decision in zip(tasks, decisions):
            if decision.action == RecoveryAction.NOOP:
                terminal.append(task.id)
                continue
            if decision.action in {RecoveryAction.REQUEUE, RecoveryAction.RESTORE}:
                recoverable.append(task.id)
            if decision.resource_reconciliation_required and self._resources.is_active(task.id):
                self._resources.cancel(task.id)
                released.append(task.id)

        return CrashRecoveryReport(
            decisions=decisions,
            released_task_ids=tuple(released),
            recoverable_task_ids=tuple(recoverable),
            terminal_task_ids=tuple(terminal),
        )
