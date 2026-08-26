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

    @property
    def remaining(self) -> int:
        return max(0, self.soft_limit - self.decisions)

    @property
    def approaching_limit(self) -> bool:
        return self.decisions >= self.soft_limit


class ToolLoopDecisionBudget:
    """Track decision turns without forcibly terminating a healthy task.

    This is intentionally a *soft* budget: callers decide what action to take
    when the budget is exhausted. That keeps correctness decisions outside the
    counter and allows recovery/failure handling to continue when necessary.
    """

    def __init__(self, config: ToolLoopDecisionBudgetConfig | None = None) -> None:
        self.config = config or ToolLoopDecisionBudgetConfig()
        self._decisions = 0

    @property
    def decisions(self) -> int:
        return self._decisions

    @property
    def state(self) -> ToolLoopDecisionBudgetState:
        return ToolLoopDecisionBudgetState(
            decisions=self._decisions,
            soft_limit=self.config.soft_limit,
        )

    def record(self) -> ToolLoopDecisionBudgetState:
        self._decisions += 1
        return self.state

    def should_checkpoint(self) -> bool:
        return self._decisions > 0 and self._decisions % self.config.checkpoint_interval == 0

    def should_prioritize_evidence_reuse(self) -> bool:
        return self._decisions >= self.config.soft_limit
