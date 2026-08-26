from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _task_metrics() -> RealDeveloperTaskMetrics:
    telemetry = (
        {"execution_id": "1", "tool_name": "read_file", "category": "exploration", "result_chars": 100},
        {"execution_id": "2", "tool_name": "write_file", "category": "progress_producing", "result_chars": 20},
        {"execution_id": "3", "tool_name": "pytest", "category": "verification", "result_chars": 200},
        {"execution_id": "4", "tool_name": "read_file", "category": "exact_duplicate", "duplicate_of": "1", "result_chars": 100},
        {"execution_id": "5", "tool_name": "run_command", "category": "failure_recovery", "retry_of": "3", "duplicate_of": "3", "result_chars": 80},
    )
    return RealDeveloperTaskMetrics(
        task_id="TASK-CLASSIFY-001",
        developer_id="developer-1",
        duration_seconds=10.0,
        llm_calls=4,
        tool_calls=5,
        unique_tool_calls=3,
        duplicate_tool_calls=2,
        retry_tool_calls=1,
        tool_result_chars=500,
        largest_tool_result_chars=200,
        tool_loop_telemetry=telemetry,
    )


def test_task_tool_loop_ratios_are_derived_from_counts() -> None:
    metrics = _task_metrics()

    assert metrics.unique_tool_call_ratio == 0.6
    assert metrics.duplicate_tool_call_ratio == 0.4
    assert metrics.retry_tool_call_ratio == 0.2
    assert metrics.avg_tool_result_chars == 100.0


def test_task_tool_loop_category_counts_are_deterministic() -> None:
    metrics = _task_metrics()

    assert metrics.tool_call_category_counts == {
        "exact_duplicate": 1,
        "exploration": 1,
        "failure_recovery": 1,
        "progress_producing": 1,
        "verification": 1,
    }


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


def test_telemetry_length_must_match_tool_calls() -> None:
    try:
        RealDeveloperTaskMetrics(
            task_id="TASK-CLASSIFY-003",
            developer_id="developer-1",
            duration_seconds=1.0,
            tool_calls=2,
            tool_loop_telemetry=({"category": "exploration"},),
        )
    except ValueError as exc:
        assert "tool_loop_telemetry" in str(exc)
    else:
        raise AssertionError("expected telemetry/tool-call mismatch to be rejected")


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

    assert result.unique_tool_calls == 3
    assert result.duplicate_tool_calls == 2
    assert result.retry_tool_calls == 1
    assert result.unique_tool_call_ratio == 0.6
    assert result.duplicate_tool_call_ratio == 0.4
    assert result.retry_tool_call_ratio == 0.2
    assert result.avg_tool_result_chars == 100.0
    assert result.tool_call_category_counts == task.tool_call_category_counts

    data = result.to_dict()
    assert data["unique_tool_call_ratio"] == 0.6
    assert data["duplicate_tool_call_ratio"] == 0.4
    assert data["retry_tool_call_ratio"] == 0.2
    assert data["avg_tool_result_chars"] == 100.0
    assert data["tool_call_category_counts"] == task.tool_call_category_counts
