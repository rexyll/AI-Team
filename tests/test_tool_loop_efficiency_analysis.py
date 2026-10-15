from benchmarks.real_developer.efficiency_analysis import (
    baseline_snapshot,
    identify_efficiency_candidates,
)
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _result() -> RealDeveloperBenchmarkResult:
    task = RealDeveloperTaskMetrics(
        task_id="TASK-001",
        developer_id="developer-1",
        duration_seconds=10.0,
        llm_calls=4,
        input_tokens=1000,
        output_tokens=100,
        llm_latency_seconds=9.5,
        tool_calls=31,
        unique_tool_calls=28,
        duplicate_tool_calls=3,
        retry_tool_calls=0,
        tool_result_chars=45908,
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


def test_baseline_snapshot_contains_deterministic_count_and_ratio_fields():
    snapshot = baseline_snapshot(_result())

    assert snapshot["scenario"] == "serial"
    assert snapshot["llm_calls"] == 4
    assert snapshot["tool_calls"] == 31
    assert snapshot["duplicate_tool_calls"] == 3
    assert snapshot["duplicate_tool_call_ratio"] == 3 / 31
    assert snapshot["retry_tool_calls"] == 0


def test_efficiency_analysis_reports_duplicate_and_multi_turn_signals_without_calling_them_proven_unnecessary():
    findings = identify_efficiency_candidates(_result())

    kinds = {item.kind for item in findings}
    assert "duplicate_tool_execution" in kinds
    assert "multi_turn_llm_execution" in kinds
    assert "llm_dominant_wall_time" in kinds

    duplicate = next(item for item in findings if item.kind == "duplicate_tool_execution")
    assert duplicate.observed == 3 / 31
    assert "could be reused" in duplicate.message


def test_efficiency_analysis_is_empty_when_no_hotspot_is_observed():
    task = RealDeveloperTaskMetrics(
        task_id="TASK-002",
        developer_id="developer-1",
        duration_seconds=1.0,
        llm_calls=1,
        tool_calls=0,
    )
    result = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=1.0,
        task_metrics=(task,),
    )

    assert identify_efficiency_candidates(result) == ()
