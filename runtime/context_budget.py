from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.context_tiers import SemanticContextTiers, TIER_NAMES


@dataclass(frozen=True)
class ContextBudgetConfig:
    """Token budget policy for semantic context tiers.

    The values are intentionally conservative: stable contracts and current
    work evidence are protected first; historical material is the first tier
    to shrink when the total budget is tight.
    """

    total_tokens: int = 6000
    minimum_tokens: tuple[tuple[str, int], ...] = (
        ("system_contract", 400),
        ("project_facts", 300),
        ("task_facts", 700),
        ("current_work_evidence", 1400),
        ("recent_interaction", 900),
        ("historical_evidence", 300),
    )

    def __post_init__(self) -> None:
        if self.total_tokens <= 0:
            raise ValueError("total_tokens must be positive")
        names = [name for name, _ in self.minimum_tokens]
        if tuple(names) != TIER_NAMES:
            raise ValueError("minimum_tokens must contain every context tier exactly once")
        if any(value < 0 for _, value in self.minimum_tokens):
            raise ValueError("minimum tier budgets must be non-negative")
        if sum(value for _, value in self.minimum_tokens) > self.total_tokens:
            raise ValueError("minimum tier budgets exceed total_tokens")


@dataclass(frozen=True)
class ContextBudgetAllocation:
    total_tokens: int
    budgets: dict[str, int]
    omitted_tiers: tuple[str, ...]

    def budget_for(self, tier: str) -> int:
        if tier not in TIER_NAMES:
            raise KeyError(tier)
        return self.budgets.get(tier, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "budgets": dict(self.budgets),
            "omitted_tiers": list(self.omitted_tiers),
        }


class ContextBudgetAllocator:
    """Allocate a bounded prompt budget according to semantic importance.

    Allocation is deterministic. Minimum budgets are reserved first, then any
    remaining capacity is distributed by tier priority. The allocator does not
    mutate or truncate the context itself; a later renderer can use these
    budgets to select content within each tier.
    """

    _PRIORITY = TIER_NAMES

    def __init__(self, config: ContextBudgetConfig | None = None) -> None:
        self.config = config or ContextBudgetConfig()

    def allocate(self, tiers: SemanticContextTiers) -> ContextBudgetAllocation:
        del tiers  # content-aware sizing belongs to the renderer, not allocation.
        budgets = {name: minimum for name, minimum in self.config.minimum_tokens}
        remaining = self.config.total_tokens - sum(budgets.values())

        # Stable priority-weighted distribution. Earlier tiers receive more
        # capacity without starving lower-priority tiers.
        weights = {
            "system_contract": 6,
            "project_facts": 4,
            "task_facts": 7,
            "current_work_evidence": 10,
            "recent_interaction": 5,
            "historical_evidence": 2,
        }
        total_weight = sum(weights.values())
        distributed = 0
        for name in self._PRIORITY:
            if name == self._PRIORITY[-1]:
                extra = remaining - distributed
            else:
                extra = remaining * weights[name] // total_weight
                distributed += extra
            budgets[name] += extra

        return ContextBudgetAllocation(
            total_tokens=self.config.total_tokens,
            budgets=budgets,
            omitted_tiers=tuple(name for name in TIER_NAMES if budgets[name] == 0),
        )
