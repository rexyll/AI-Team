from __future__ import annotations

from typing import Any

from runtime.developer_decision_trace_collector import DeveloperDecisionTraceCollector


def record_developer_decision_trace(
    collector: DeveloperDecisionTraceCollector,
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
) -> None:
    """Best-effort integration seam for DeveloperAgent observability.

    Trace collection is deliberately side-channel: instrumentation failures
    must never alter the Developer execution path.
    """
    try:
        collector.record(
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
    except Exception:
        # Observability must remain non-blocking.
        return
