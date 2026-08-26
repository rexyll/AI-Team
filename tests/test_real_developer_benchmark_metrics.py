from benchmarks.real_developer.metrics import (
    RealDeveloperBenchmarkResult,
    RealDeveloperTaskMetrics,
)


def test_task_metrics_aggregate_tokens_and_calls():
    metrics = RealDeveloperTaskMetrics(
        task_id="TASK-1",
        developer_id="developer-1",
        duration_seconds=1.5,
        llm_calls=2,
        input_tokens=100,
        output_tokens=40,
    )
    result = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="independent",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=1.5,
        task_metrics=(metrics,),
    )

    assert result.llm_calls == 2
    assert result.total_tokens == 140
    assert result.developer_utilization == 1.0
    assert result.cost_per_completed_task_tokens == 140


def test_developer_utilization_uses_task_busy_time():
    metrics = (
        RealDeveloperTaskMetrics("A", "developer-1", 1.0),
        RealDeveloperTaskMetrics("B", "developer-2", 0.5),
    )
    result = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="parallel",
        developer_count=2,
        task_count=2,
        completed=2,
        failed=0,
        blocked=0,
        duration_seconds=1.0,
        task_metrics=metrics,
    )

    assert result.developer_utilization == 0.75
