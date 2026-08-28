from __future__ import annotations

from typing import Any

from runtime.developer_decision_trace import DeveloperDecisionTrace, build_developer_decision_trace


class DeveloperDecisionTraceCollector:
    """Side-channel collector that never participates in tool execution."""

    def __init__(self) -> None:
        self._traces: list[DeveloperDecisionTrace] = []

    @property
    def traces(self) -> tuple[DeveloperDecisionTrace, ...]:
        return tuple(self._traces)

    def record(
        self,
        *,
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
        trace = build_developer_decision_trace(
            decision_index=len(self._traces) + 1,
            tool_calls=tool_calls,
            cache_hits=cache_hits,
            verification_reuses=verification_reuses,
            batched_calls=batched_calls,
            logical_cost=logical_cost,
            budget_state=budget_state,
            evidence_sources=evidence_sources,
            convergence_reason=convergence_reason,
            correctness_override=correctness_override,
            metadata=metadata,
        )
        self._traces.append(trace)
        return trace

    def to_dict(self) -> list[dict[str, Any]]:
        return [trace.to_dict() for trace in self._traces]
