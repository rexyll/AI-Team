from benchmarks.real_developer.efficiency_analysis import baseline_snapshot
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _result() -> RealDeveloperBenchmarkResult:
    task_a = RealDeveloperTaskMetrics(
        task_id="TASK-001",
        developer_id="developer-1",
        duration_seconds=2.0,
        llm_calls=2,
        tool_calls=1,
        developer_decision_trace=(
            {"convergence_reason": "new_evidence_requires_reasoning"},
            {"convergence_reason": "terminal_verification"},
        ),
    )
    task_b = RealDeveloperTaskMetrics(
        task_id="TASK-002",
        developer_id="developer-1",
        duration_seconds=1.0,
        llm_calls=1,
        tool_calls=1,
        developer_decision_trace=(
            {"convergence_reason": "new_evidence_requires_reasoning"},
        ),
    )
    return RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=2,
        completed=2,
        failed=0,
        blocked=0,
        duration_seconds=3.0,
        task_metrics=(task_a, task_b),
    )


def test_decision_trace_reason_counts_are_aggregated_deterministically():
    result = _result()

    assert result.decision_trace_count == 3
    assert result.decision_trace_reason_counts == {
        "new_evidence_requires_reasoning": 2,
        "terminal_verification": 1,
    }


def test_baseline_snapshot_exposes_decision_trace_summary():
    snapshot = baseline_snapshot(_result())

    assert snapshot["llm_decision_trace_count"] == 3
    assert snapshot["llm_decision_trace_reason_counts"]["terminal_verification"] == 1
