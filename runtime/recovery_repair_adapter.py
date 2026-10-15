from __future__ import annotations

from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.task_manager import TaskManager
from runtime.workflow_transition import WorkflowOutcomeKind, get_workflow_transition


class RecoveryRepairAdapter:
    """Bridge a REPAIR recovery intent into the existing revision lifecycle."""

    def __init__(self, task_manager: TaskManager) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        self.task_manager = task_manager

    def apply(self, intent: RecoveryIntent) -> None:
        """Apply REPAIR using the existing reviewer revision transition only."""
        if not isinstance(intent, RecoveryIntent):
            raise TypeError("intent must be a RecoveryIntent")
        if intent.action is not RecoveryAction.REPAIR:
            raise ValueError("RecoveryRepairAdapter requires a REPAIR intent")

        transition = get_workflow_transition("reviewer", WorkflowOutcomeKind.REVISION_REQUIRED)
        task = self.task_manager.get_task(intent.task_id)
        if task.status != transition.source.value:
            raise ValueError(
                f"REPAIR requires task status {transition.source.value!r}, got {task.status!r}"
            )
        self.task_manager.transition(intent.task_id, transition.target)
