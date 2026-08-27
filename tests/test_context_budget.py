import pytest

from runtime.context_budget import ContextBudgetAllocator, ContextBudgetConfig
from runtime.context_tiers import SemanticContextTiers


def _tiers() -> SemanticContextTiers:
    return SemanticContextTiers(
        system_contract={"role": "developer"},
        project_facts={"project": "demo"},
        task_facts={"task_id": "TASK-1"},
        current_work_evidence={"changed_files": ["runtime/task.py"]},
        recent_interaction=[{"tool": "read_file"}],
        historical_evidence={"tests": ["passed"]},
    )


def test_allocation_is_bounded_and_covers_every_tier() -> None:
    allocation = ContextBudgetAllocator().allocate(_tiers())

    assert sum(allocation.budgets.values()) == 6000
    assert tuple(allocation.budgets) == (
        "system_contract",
        "project_facts",
        "task_facts",
        "current_work_evidence",
        "recent_interaction",
        "historical_evidence",
    )
    assert allocation.omitted_tiers == ()


def test_current_work_and_task_receive_more_capacity_than_history() -> None:
    allocation = ContextBudgetAllocator().allocate(_tiers())

    assert allocation.budget_for("current_work_evidence") > allocation.budget_for("historical_evidence")
    assert allocation.budget_for("task_facts") > allocation.budget_for("historical_evidence")


def test_allocation_is_deterministic() -> None:
    allocator = ContextBudgetAllocator(ContextBudgetConfig(total_tokens=2048))
    first = allocator.allocate(_tiers())
    second = allocator.allocate(_tiers())

    assert first == second
    assert sum(first.budgets.values()) == 2048


def test_invalid_budget_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="minimum tier budgets exceed"):
        ContextBudgetConfig(total_tokens=1000)

    with pytest.raises(ValueError, match="every context tier"):
        ContextBudgetConfig(total_tokens=6000, minimum_tokens=(("task_facts", 1),) * 6)


def test_budget_lookup_rejects_unknown_tier() -> None:
    allocation = ContextBudgetAllocator().allocate(_tiers())

    with pytest.raises(KeyError):
        allocation.budget_for("unknown")
