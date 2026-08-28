from runtime.developer_decision_trace import build_developer_decision_trace


def test_trace_serializes_decision_evidence_and_budget_state():
    trace = build_developer_decision_trace(
        decision_index=2,
        tool_calls=4,
        cache_hits=2,
        verification_reuses=1,
        batched_calls=2,
        logical_cost=2,
        budget_state="healthy",
        evidence_sources=["cache", "batch", "workspace"],
    )
    assert trace.to_dict() == {
        "decision_index": 2,
        "tool_calls": 4,
        "cache_hits": 2,
        "verification_reuses": 1,
        "batched_calls": 2,
        "logical_cost": 2,
        "budget_state": "healthy",
        "evidence_sources": ["cache", "batch", "workspace"],
        "convergence_reason": None,
        "correctness_override": False,
        "metadata": {},
    }


def test_trace_deduplicates_evidence_sources_deterministically():
    trace = build_developer_decision_trace(
        decision_index=1,
        tool_calls=1,
        evidence_sources=["cache", "cache", "workspace", "cache"],
    )
    assert trace.evidence_sources == ("cache", "workspace")


def test_trace_rejects_invalid_counters():
    try:
        build_developer_decision_trace(decision_index=0, tool_calls=1)
    except ValueError as exc:
        assert "decision_index" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    try:
        build_developer_decision_trace(decision_index=1, tool_calls=1, cache_hits=2)
    except ValueError as exc:
        assert "cache_hits" in str(exc)
    else:
        raise AssertionError("expected ValueError")
