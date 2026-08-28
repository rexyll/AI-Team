from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolLoopDecisionBudgetConfig:
    """Soft budget for LLM decision turns within one task."""

    soft_limit: int = 12
    checkpoint_interval: int = 4

    def __post_init__(self) -> None:
        if self.soft_limit < 1:
            raise ValueError("soft_limit must be >= 1")
        if self.checkpoint_interval < 1:
            raise ValueError("checkpoint_interval must be >= 1")


@dataclass(frozen=True)
class ToolLoopDecisionBudgetState:
    """Immutable snapshot exposed to the orchestration layer."""

    decisions: int
    soft_limit: int
    logical_cost: int = 0
    correctness_override: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.soft_limit - self.decisions)

    @property
    def approaching_limit(self) -> bool:
        return self.decisions >= self.soft_limit

    @property
    def should_converge(self) -> bool:
        return self.approaching_limit and not self.correctness_override


class ToolLoopDecisionBudget:
    """Track decision turns as a soft budget, never as a correctness gate."""

    def __init__(self, config: ToolLoopDecisionBudgetConfig | None = None) -> None:
        self.config = config or ToolLoopDecisionBudgetConfig()
        self._decisions = 0
        self._logical_cost = 0

    @property
    def decisions(self) -> int:
        return self._decisions

    @property
    def state(self) -> ToolLoopDecisionBudgetState:
        return ToolLoopDecisionBudgetState(
            decisions=self._decisions,
            soft_limit=self.config.soft_limit,
            logical_cost=self._logical_cost,
        )

    def record(self, logical_cost: int = 1) -> ToolLoopDecisionBudgetState:
        if logical_cost < 0:
            raise ValueError("logical_cost must be >= 0")
        self._decisions += 1
        self._logical_cost += logical_cost
        return self.state

    def should_checkpoint(self) -> bool:
        return self._decisions > 0 and self._decisions % self.config.checkpoint_interval == 0

    def should_prioritize_evidence_reuse(self) -> bool:
        return self._decisions >= self.config.soft_limit

    def should_converge(self, *, correctness_risk: bool = False) -> bool:
        return self._decisions >= self.config.soft_limit and not correctness_risk

    def override_for_correctness(self) -> ToolLoopDecisionBudgetState:
        return ToolLoopDecisionBudgetState(
            decisions=self._decisions,
            soft_limit=self.config.soft_limit,
            logical_cost=self._logical_cost,
            correctness_override=True,
        )


def decision_logical_cost(
    *,
    tool_calls: int = 0,
    cache_hits: int = 0,
    verification_calls: int = 0,
) -> int:
    """Return exploration cost without charging cache hits or verification."""
    if min(tool_calls, cache_hits, verification_calls) < 0:
        raise ValueError("decision cost components must be non-negative")
    return max(0, tool_calls - cache_hits - verification_calls)
