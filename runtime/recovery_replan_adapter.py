from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from runtime.dependency_graph import build_dependency_graph, topological_sort
from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.task_validator import validate_plan


@dataclass(frozen=True)
class ReplanResult:
    """Validated replacement-plan candidate produced by a REPLAN intent."""

    task_id: str
    plan: dict[str, Any]
    execution_order: tuple[str, ...]
    failure_reason: str
    failure_class: str
    attempt: int


class RecoveryReplanAdapter:
    """Prepare a validated re-plan without mutating the live task graph.

    Planner execution and plan validation belong to the planning boundary;
    replacing a live TaskManager graph is deliberately a later integration
    step. This adapter therefore returns an immutable result and performs no
    task lifecycle mutation.
    """

    def __init__(self, planner: Callable[[str], dict[str, Any]]):
        if not callable(planner):
            raise TypeError("planner must be callable")
        self._planner = planner

    def prepare(self, intent: RecoveryIntent, requirement: str) -> ReplanResult:
        if not isinstance(intent, RecoveryIntent):
            raise TypeError("intent must be a RecoveryIntent")
        if intent.action is not RecoveryAction.REPLAN:
            raise ValueError("RecoveryReplanAdapter requires a REPLAN intent")
        if not isinstance(requirement, str) or not requirement.strip():
            raise ValueError("requirement must be a non-empty string")

        plan = self._planner(requirement)
        if not isinstance(plan, dict):
            raise ValueError("planner must return a plan dictionary")
        validate_plan(plan)

        graph = build_dependency_graph(plan["tasks"])
        execution_order = tuple(topological_sort(graph))

        return ReplanResult(
            task_id=intent.task_id,
            plan=plan,
            execution_order=execution_order,
            failure_reason=intent.failure_reason,
            failure_class=intent.failure_class.value,
            attempt=intent.attempt,
        )
