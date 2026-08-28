from runtime.tool_loop_decision_budget import (
    ToolLoopDecisionBudget,
    ToolLoopDecisionBudgetConfig,
    decision_logical_cost,
)


def test_cache_hits_reduce_logical_exploration_cost():
    assert decision_logical_cost(tool_calls=4, cache_hits=3) == 1


def test_verification_reuse_does_not_consume_exploration_budget():
    assert decision_logical_cost(tool_calls=3, verification_calls=3) == 0


def test_safe_batch_cost_is_logical_observations_not_worker_count():
    assert decision_logical_cost(tool_calls=3, batched_calls=3) == 3


def test_budget_converges_on_logical_cost_not_physical_decision_count():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=3))
    budget.record(logical_cost=2)
    assert budget.should_converge() is False
    budget.record(logical_cost=1)
    assert budget.should_converge() is True


def test_correctness_risk_can_override_budget_convergence():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=1))
    budget.record(logical_cost=1)
    assert budget.should_converge(correctness_risk=True) is False
    state = budget.override_for_correctness()
    assert state.correctness_override is True
    assert state.logical_cost == 1
