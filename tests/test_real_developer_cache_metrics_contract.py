from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _task_metrics() -> RealDeveloperTaskMetrics:
    return RealDeveloperTaskMetrics(
        task_id="TASK-1",
        developer_id="developer-1",
        duration_seconds=1.0,
        tool_calls=4,
        unique_tool_calls=3,
        duplicate_tool_calls=1,
        cache_hits=2,
        cache_misses=3,
        cache_invalidations=1,
    )


def test_task_cache_metrics_are_exposed_and_ratio_is_stable():
    metrics = _task_metrics()

    assert metrics.cache_hits == 2
    assert metrics.cache_misses == 3
    assert metrics.cache_invalidations == 1
    assert metrics.cache_hit_ratio == 0.4


def test_benchmark_aggregates_cache_metrics():
    metrics = _task_metrics()
    result = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=1.0,
        task_metrics=(metrics,),
    )

    assert result.cache_hits == 2
    assert result.cache_misses == 3
    assert result.cache_invalidations == 1
    assert result.cache_hit_ratio == 0.4
    payload = result.to_dict()
    assert payload["cache_hits"] == 2
    assert payload["cache_misses"] == 3
    assert payload["cache_invalidations"] == 1
    assert payload["cache_hit_ratio"] == 0.4
