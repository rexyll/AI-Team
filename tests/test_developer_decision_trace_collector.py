from runtime.developer_decision_trace_collector import DeveloperDecisionTraceCollector


def test_collector_assigns_deterministic_decision_indexes():
    collector = DeveloperDecisionTraceCollector()
    first = collector.record(tool_calls=2, logical_cost=2)
    second = collector.record(tool_calls=1, cache_hits=1, logical_cost=0)

    assert first.decision_index == 1
    assert second.decision_index == 2
    assert [trace.decision_index for trace in collector.traces] == [1, 2]


def test_collector_is_side_channel_and_serializable():
    collector = DeveloperDecisionTraceCollector()
    collector.record(
        tool_calls=3,
        cache_hits=1,
        verification_reuses=1,
        batched_calls=2,
        logical_cost=1,
        budget_state="elevated",
        evidence_sources=["read_file:a", "read_file:a"],
        metadata={"source": "developer"},
    )

    assert collector.to_dict() == [
        {
            "decision_index": 1,
            "tool_calls": 3,
            "cache_hits": 1,
            "verification_reuses": 1,
            "batched_calls": 2,
            "logical_cost": 1,
            "budget_state": "elevated",
            "evidence_sources": ["read_file:a"],
            "convergence_reason": None,
            "correctness_override": False,
            "metadata": {"source": "developer"},
        }
    ]
