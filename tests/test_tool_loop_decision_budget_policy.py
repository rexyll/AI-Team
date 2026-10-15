import pytest

from runtime.tool_loop_decision_budget import (
    ToolLoopDecisionBudget,
    ToolLoopDecisionBudgetConfig,
    decision_logical_cost,
)


def test_budget_tracks_decision_and_logical_cost():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=3, checkpoint_interval=2))
    assert budget.state.decisions == 0
    assert budget.state.logical_cost == 0
    state = budget.record(logical_cost=2)
    assert state.decisions == 1
    assert state.logical_cost == 2
    assert state.should_converge is False


def test_soft_limit_requests_convergence_without_blocking_correctness():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=2))
    budget.record()
    assert budget.should_converge() is False
    budget.record()
    assert budget.should_converge() is True
    assert budget.should_converge(correctness_risk=True) is False
    assert budget.override_for_correctness().correctness_override is True


def test_checkpoint_interval_remains_decision_based():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=8, checkpoint_interval=2))
    budget.record()
    assert budget.should_checkpoint() is False
    budget.record()
    assert budget.should_checkpoint() is True


def test_logical_cost_excludes_cache_hits_and_verification():
    assert decision_logical_cost(tool_calls=5, cache_hits=2, verification_calls=1) == 2
    assert decision_logical_cost(tool_calls=2, cache_hits=5) == 0


@pytest.mark.parametrize("kwargs", [
    {"tool_calls": -1},
    {"cache_hits": -1},
    {"verification_calls": -1},
])
def test_logical_cost_rejects_negative_components(kwargs):
    with pytest.raises(ValueError):
        decision_logical_cost(**kwargs)
