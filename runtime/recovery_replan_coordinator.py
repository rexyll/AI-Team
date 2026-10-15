from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from runtime.failure_recovery_executor import RecoveryIntent
from runtime.recovery_replan_acceptance import ReplanAcceptance, accept_replan
from runtime.recovery_replan_adapter import RecoveryReplanAdapter, ReplanResult
from runtime.recovery_replan_replacement import ReplanGraphReplacement, materialize_replacement
from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class ReplanOutcome:
    """Validated replacement candidate; live task state is changed only by commit."""

    result: ReplanResult
    acceptance: ReplanAcceptance
    replacement: ReplanGraphReplacement


class RecoveryReplanCoordinator:
    """Own the complete, side-effect-free preparation of a recovery re-plan."""

    def __init__(self, manager: TaskManager, planner: Callable[[str], dict[str, Any]]) -> None:
        if not isinstance(manager, TaskManager):
            raise TypeError("manager must be a TaskManager")
        if not callable(planner):
            raise TypeError("planner must be callable")
        self.manager = manager
        self.adapter = RecoveryReplanAdapter(planner)

    def prepare(self, intent: RecoveryIntent, requirement: str) -> ReplanOutcome:
        if not isinstance(intent, RecoveryIntent):
            raise TypeError("intent must be a RecoveryIntent")
        if not requirement.strip():
            raise ValueError("requirement must be a non-empty string")
        result = self.adapter.prepare(intent, requirement)
        acceptance = accept_replan(self.manager, result)
        replacement = materialize_replacement(self.manager, acceptance)
        return ReplanOutcome(
            result=result,
            acceptance=acceptance,
            replacement=replacement,
        )

    def commit(self, outcome: ReplanOutcome) -> None:
        if not isinstance(outcome, ReplanOutcome):
            raise TypeError("outcome must be a ReplanOutcome")
        self.manager.replace_task_graph(outcome.replacement.tasks)
