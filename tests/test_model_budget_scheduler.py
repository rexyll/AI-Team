import pytest

from runtime.model_budget_scheduler import (
    ModelBudgetProjectScheduler,
    ModelBudgetSchedulingDecision,
)
from runtime.model_governance import (
    ModelGovernance,
    ModelGovernancePolicy,
    ModelRoute,
    ModelUsage,
    ProjectModelBudget,
)
from runtime.model_usage import ModelUsageLedger
from runtime.project_scheduler import ProjectExecutionScope, ProjectScheduler
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task


def _scheduler(project_id: str = "P1", task_id: str = "A") -> ProjectScheduler:
    task = Task(task_id, task_id, "task", "developer", context={"project_id": project_id})
    return ProjectScheduler(
        ProjectExecutionScope(project_id),
        [task],
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)),
    )


def _governance(*, budget: ProjectModelBudget | None = None, fallback: ModelRoute | None = None) -> ModelGovernance:
    primary = ModelRoute("agnes", "primary")
    return ModelGovernance(
        [
            ModelGovernancePolicy(
                "P1",
                primary,
                budget or ProjectModelBudget(1000, 1000, 5),
                fallback,
            )
        ]
    )


def test_admits_only_when_both_project_and_model_budgets_allow() -> None:
    adapter = ModelBudgetProjectScheduler(
        _scheduler(),
        _governance(),
        ModelUsageLedger(),
    )

    decision = adapter.decide("A", model_request=ModelUsage(input_tokens=10, output_tokens=20, llm_calls=1))

    assert decision == ModelBudgetSchedulingDecision(
        ProjectExecutionScope("P1"), "A", True, ModelRoute("agnes", "primary"), None
    )


def test_model_budget_rejection_happens_after_project_admission_without_mutation() -> None:
    ledger = ModelUsageLedger()
    ledger.record("P1", ModelUsage(input_tokens=990, output_tokens=0, llm_calls=1))
    adapter = ModelBudgetProjectScheduler(_scheduler(), _governance(), ledger)

    decision = adapter.decide("A", model_request=ModelUsage(input_tokens=20, llm_calls=1))

    assert decision.admitted is False
    assert decision.reason == "project input-token budget exceeded"
    assert ledger.usage_for("P1") == ModelUsage(input_tokens=990, output_tokens=0, llm_calls=1)


def test_unhealthy_primary_returns_governance_selected_fallback() -> None:
    fallback = ModelRoute("agnes", "backup")
    adapter = ModelBudgetProjectScheduler(
        _scheduler(),
        _governance(fallback=fallback),
        ModelUsageLedger(),
    )

    decision = adapter.decide("A", model_request=ModelUsage(llm_calls=1), primary_healthy=False)

    assert decision.admitted is True
    assert decision.route == fallback
    assert decision.reason == "primary route unhealthy; fallback selected"


def test_project_admission_rejection_short_circuits_model_governance() -> None:
    scheduler = _scheduler()
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)).start_task()
    blocked_scheduler = ProjectScheduler(scheduler.scope, [scheduler.task_for("A")], governor)
    adapter = ModelBudgetProjectScheduler(blocked_scheduler, _governance(), ModelUsageLedger())

    decision = adapter.decide("A", model_request=ModelUsage(input_tokens=1, llm_calls=1))

    assert decision.admitted is False
    assert decision.reason == "concurrency resource limit exceeded"


def test_each_project_uses_its_own_model_budget() -> None:
    first_ledger = ModelUsageLedger()
    second_ledger = ModelUsageLedger()
    first_ledger.record("P1", ModelUsage(input_tokens=1000))
    first = ModelBudgetProjectScheduler(
        _scheduler("P1", "A"),
        _governance(budget=ProjectModelBudget(1000, 1000, 5)),
        first_ledger,
    )
    second_governance = ModelGovernance(
        [
            ModelGovernancePolicy(
                "P2",
                ModelRoute("agnes", "primary"),
                ProjectModelBudget(1000, 1000, 5),
            )
        ]
    )
    second = ModelBudgetProjectScheduler(
        _scheduler("P2", "B"), second_governance, second_ledger
    )

    assert first.decide("A", model_request=ModelUsage(input_tokens=1)).admitted is False
    assert second.decide("B", model_request=ModelUsage(input_tokens=1)).admitted is True
