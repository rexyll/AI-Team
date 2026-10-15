from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeveloperDecisionTrace:
    """Compact, deterministic explanation of one Developer decision turn."""

    decision_index: int
    tool_calls: int
    cache_hits: int = 0
    verification_reuses: int = 0
    batched_calls: int = 0
    logical_cost: int = 0
    budget_state: str = "healthy"
    evidence_sources: tuple[str, ...] = ()
    convergence_reason: str | None = None
    correctness_override: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_index": self.decision_index,
            "tool_calls": self.tool_calls,
            "cache_hits": self.cache_hits,
            "verification_reuses": self.verification_reuses,
            "batched_calls": self.batched_calls,
            "logical_cost": self.logical_cost,
            "budget_state": self.budget_state,
            "evidence_sources": list(self.evidence_sources),
            "convergence_reason": self.convergence_reason,
            "correctness_override": self.correctness_override,
            "metadata": dict(self.metadata),
        }


def build_developer_decision_trace(
    *,
    decision_index: int,
    tool_calls: int,
    cache_hits: int = 0,
    verification_reuses: int = 0,
    batched_calls: int = 0,
    logical_cost: int = 0,
    budget_state: str = "healthy",
    evidence_sources: list[str] | tuple[str, ...] = (),
    convergence_reason: str | None = None,
    correctness_override: bool = False,
    metadata: dict[str, Any] | None = None,
) -> DeveloperDecisionTrace:
    if decision_index < 1:
        raise ValueError("decision_index must be >= 1")
    if min(tool_calls, cache_hits, verification_reuses, batched_calls, logical_cost) < 0:
        raise ValueError("decision trace counters must be non-negative")
    if cache_hits > tool_calls:
        raise ValueError("cache_hits cannot exceed tool_calls")
    if verification_reuses > tool_calls:
        raise ValueError("verification_reuses cannot exceed tool_calls")
    if batched_calls > tool_calls:
        raise ValueError("batched_calls cannot exceed tool_calls")
    if logical_cost > tool_calls:
        raise ValueError("logical_cost cannot exceed tool_calls")
    return DeveloperDecisionTrace(
        decision_index=decision_index,
        tool_calls=tool_calls,
        cache_hits=cache_hits,
        verification_reuses=verification_reuses,
        batched_calls=batched_calls,
        logical_cost=logical_cost,
        budget_state=budget_state,
        evidence_sources=tuple(dict.fromkeys(evidence_sources)),
        convergence_reason=convergence_reason,
        correctness_override=correctness_override,
        metadata=dict(metadata or {}),
    )
