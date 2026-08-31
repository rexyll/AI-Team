from benchmarks.real_developer.efficiency_analysis import baseline_snapshot, identify_efficiency_candidates
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _result() -> RealDeveloperBenchmarkResult:
    task = RealDeveloperTaskMetrics(
        task_id="TASK-CACHE-PROBE",
        developer_id="developer-1",
        duration_seconds=5.0,
        llm_calls=2,
        input_tokens=100,
        output_tokens=20,
        llm_latency_seconds=4.0,
        tool_calls=3,
        unique_tool_calls=2,
        duplicate_tool_calls=1,
        retry_tool_calls=0,
        cache_hits=2,
        cache_misses=1,
        tool_loop_telemetry=(
            {"category": "exploration"},
            {"category": "exact_duplicate"},
            {"category": "exploration"},
        ),
    )
    return RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=5.0,
        task_metrics=(task,),
    )


def test_snapshot_reports_cache_probe_excess() -> None:
    snapshot = baseline_snapshot(_result())
    assert snapshot["exact_duplicate_tool_calls"] == 1
    assert snapshot["cache_hits"] == 2
    assert snapshot["cache_probe_excess"] == 1


def test_efficiency_analysis_reports_redundant_cache_probe() -> None:
    findings = identify_efficiency_candidates(_result())
    finding = next(item for item in findings if item.kind == "redundant_cache_probe")
    assert finding.observed == 1.0
    assert "probe the cache more than once" in finding.message
