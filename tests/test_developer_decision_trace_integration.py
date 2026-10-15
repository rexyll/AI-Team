from __future__ import annotations

from runtime.developer_decision_trace_collector import DeveloperDecisionTraceCollector
from runtime.developer_decision_trace_integration import record_developer_decision_trace


def test_integration_records_one_trace_per_decision():
    collector = DeveloperDecisionTraceCollector()
    record_developer_decision_trace(
        collector,
        tool_calls=2,
        cache_hits=1,
        logical_cost=1,
        evidence_sources=("runtime/task.py", "runtime/task.py"),
    )
    record_developer_decision_trace(
        collector,
        tool_calls=1,
        verification_reuses=1,
        logical_cost=0,
        budget_state="approaching_limit",
        convergence_reason="verification_reused",
    )

    traces = collector.to_dict()
    assert len(traces) == 2
    assert [trace["decision_index"] for trace in traces] == [1, 2]
    assert traces[0]["cache_hits"] == 1
    assert traces[0]["logical_cost"] == 1
    assert traces[0]["evidence_sources"] == ["runtime/task.py"]
    assert traces[1]["verification_reuses"] == 1
    assert traces[1]["logical_cost"] == 0
    assert traces[1]["convergence_reason"] == "verification_reused"


def test_integration_is_non_blocking_when_collector_fails():
    class BrokenCollector:
        def record(self, **kwargs):
            raise RuntimeError("observability failure")

    # The integration seam must swallow instrumentation failures.
    assert record_developer_decision_trace(
        BrokenCollector(), tool_calls=1, logical_cost=1
    ) is None
