import pytest

from runtime.tool_loop_decision_budget import (
    ToolLoopDecisionBudget,
    ToolLoopDecisionBudgetConfig,
)


def test_budget_counts_decisions_and_exposes_remaining_capacity():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=3))

    assert budget.decisions == 0
    assert budget.state.remaining == 3
    assert not budget.state.approaching_limit

    budget.record()
    budget.record()
    state = budget.record()

    assert state.decisions == 3
    assert state.remaining == 0
    assert state.approaching_limit


def test_checkpoint_interval_is_independent_from_soft_limit():
    budget = ToolLoopDecisionBudget(
        ToolLoopDecisionBudgetConfig(soft_limit=10, checkpoint_interval=2)
    )

    assert not budget.should_checkpoint()
    budget.record()
    assert not budget.should_checkpoint()
    budget.record()
    assert budget.should_checkpoint()
    budget.record()
    assert not budget.should_checkpoint()
    budget.record()
    assert budget.should_checkpoint()


def test_budget_does_not_force_termination():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=1))

    budget.record()
    budget.record()
    budget.record()

    assert budget.decisions == 3
    assert budget.should_prioritize_evidence_reuse()
    assert budget.state.remaining == 0


def test_invalid_budget_configuration_is_rejected():
    with pytest.raises(ValueError, match="soft_limit"):
        ToolLoopDecisionBudgetConfig(soft_limit=0)

    with pytest.raises(ValueError, match="checkpoint_interval"):
        ToolLoopDecisionBudgetConfig(checkpoint_interval=0)
