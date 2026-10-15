from benchmarks.real_developer.efficiency_analysis import (
    baseline_snapshot,
    identify_efficiency_candidates,
)
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _result() -> RealDeveloperBenchmarkResult:
    telemetry = (
        {"category": "exploration"},
        {"category": "exact_duplicate"},
        {"category": "failure_recovery"},
        {"category": "verification"},
    )
    task = RealDeveloperTaskMetrics(
        task_id="TASK-001",
        developer_id="developer-1",
        duration_seconds=10.0,
        llm_calls=2,
        input_tokens=100,
        output_tokens=20,
        llm_latency_seconds=9.5,
        tool_calls=4,
        unique_tool_calls=3,
        duplicate_tool_calls=2,
        retry_tool_calls=1,
        tool_loop_telemetry=telemetry,
    )
    return RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=10.0,
        task_metrics=(task,),
    )


def test_baseline_snapshot_exposes_exact_duplicate_category_without_relabeling_retries():
    snapshot = baseline_snapshot(_result())
    assert snapshot["duplicate_tool_calls"] == 2
    assert snapshot["retry_tool_calls"] == 1
    assert snapshot["exact_duplicate_tool_calls"] == 1
    assert snapshot["tool_call_category_counts"]["failure_recovery"] == 1


def test_efficiency_candidates_target_exact_duplicates_not_failure_recovery():
    findings = identify_efficiency_candidates(_result())
    duplicate = next(item for item in findings if item.kind == "duplicate_tool_execution")
    assert duplicate.observed == 0.25
    assert "Failure-recovery retries are excluded" in duplicate.message
