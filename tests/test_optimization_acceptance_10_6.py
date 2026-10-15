from __future__ import annotations

from runtime.tool_loop_decision_budget import (
    ToolLoopDecisionBudget,
    ToolLoopDecisionBudgetConfig,
    decision_logical_cost,
)
from runtime.tool_loop_batch import SAFE_BATCH_TOOLS


def test_10_6_acceptance_has_single_safe_batch_allowlist():
    assert SAFE_BATCH_TOOLS == frozenset({"list_files", "read_file"})


def test_10_6_acceptance_cache_and_verification_do_not_add_exploration_cost():
    assert decision_logical_cost(tool_calls=6, cache_hits=3, verification_calls=2) == 1


def test_10_6_acceptance_batch_preserves_logical_evidence_cost():
    assert decision_logical_cost(tool_calls=4, batched_calls=4) == 4


def test_10_6_acceptance_budget_converges_only_after_logical_cost_limit():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=4))
    budget.record(3)
    assert budget.should_prioritize_evidence_reuse() is False
    assert budget.should_converge() is False
    budget.record(1)
    assert budget.should_prioritize_evidence_reuse() is True
    assert budget.should_converge() is True


def test_10_6_acceptance_correctness_can_override_convergence():
    budget = ToolLoopDecisionBudget(ToolLoopDecisionBudgetConfig(soft_limit=1))
    budget.record(1)
    assert budget.should_converge(correctness_risk=True) is False
