from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _task_metrics() -> RealDeveloperTaskMetrics:
    return RealDeveloperTaskMetrics(
        task_id="TASK-CLASSIFY-001",
        developer_id="developer-1",
        duration_seconds=10.0,
        llm_calls=4,
        tool_calls=10,
        unique_tool_calls=7,
        duplicate_tool_calls=3,
        retry_tool_calls=1,
        tool_result_chars=4000,
        largest_tool_result_chars=1200,
    )


def test_task_tool_loop_ratios_are_derived_from_counts() -> None:
    metrics = _task_metrics()

    assert metrics.unique_tool_call_ratio == 0.7
    assert metrics.duplicate_tool_call_ratio == 0.3
    assert metrics.retry_tool_call_ratio == 0.1
    assert metrics.avg_tool_result_chars == 400.0


def test_retry_count_cannot_exceed_duplicate_count() -> None:
    try:
        RealDeveloperTaskMetrics(
            task_id="TASK-CLASSIFY-002",
            developer_id="developer-1",
            duration_seconds=1.0,
            tool_calls=2,
            unique_tool_calls=2,
            duplicate_tool_calls=0,
            retry_tool_calls=1,
        )
    except ValueError as exc:
        assert "retry_tool_calls" in str(exc)
    else:
        raise AssertionError("expected invalid retry/duplicate counts to be rejected")


def test_benchmark_aggregates_and_serializes_tool_loop_classification() -> None:
    task = _task_metrics()
    result = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=10.0,
        task_metrics=(task,),
    )

    assert result.unique_tool_calls == 7
    assert result.duplicate_tool_calls == 3
    assert result.retry_tool_calls == 1
    assert result.unique_tool_call_ratio == 0.7
    assert result.duplicate_tool_call_ratio == 0.3
    assert result.retry_tool_call_ratio == 0.1
    assert result.avg_tool_result_chars == 400.0

    data = result.to_dict()
    assert data["unique_tool_call_ratio"] == 0.7
    assert data["duplicate_tool_call_ratio"] == 0.3
    assert data["retry_tool_call_ratio"] == 0.1
    assert data["avg_tool_result_chars"] == 400.0
