from benchmarks.real_developer.llm_instrumentation import LLMCallProfile
from benchmarks.real_developer.metrics import (
    RealDeveloperBenchmarkResult,
    RealDeveloperTaskMetrics,
)


def test_task_metrics_aggregate_tokens_calls_and_execution_details():
    metrics = RealDeveloperTaskMetrics(
        task_id="TASK-1",
        developer_id="developer-1",
        duration_seconds=1.5,
        llm_calls=2,
        input_tokens=100,
        output_tokens=40,
        llm_latency_seconds=1.2,
        tool_calls=4,
        test_commands=2,
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
    assert result.llm_latency_seconds == 1.2
    assert result.avg_llm_latency_seconds == 0.6
    assert result.tool_calls == 4
    assert result.test_commands == 2
    assert result.developer_utilization == 1.0
    assert result.cost_per_completed_task_tokens == 140


def test_task_metrics_exposes_context_growth_without_storing_prompt_content():
    profiles = (
        LLMCallProfile(1, "generate_with_tools", 0.1, input_tokens=10, output_tokens=4, prompt_chars=100, message_count=2, tool_count=3),
        LLMCallProfile(2, "generate_with_tools", 0.2, input_tokens=20, output_tokens=5, prompt_chars=250, message_count=4, tool_count=3),
    )
    metrics = RealDeveloperTaskMetrics(
        task_id="TASK-PROFILE",
        developer_id="developer-1",
        duration_seconds=0.5,
        llm_calls=2,
        input_tokens=30,
        output_tokens=9,
        llm_latency_seconds=0.3,
        llm_profiles=profiles,
    )

    assert metrics.max_prompt_chars == 250
    assert metrics.max_input_tokens == 20
    assert metrics.context_growth_ratio == 2.5
    assert all(not hasattr(profile, "prompt") for profile in metrics.llm_profiles)


def test_benchmark_result_aggregates_context_profile_metrics():
    profiles = (
        LLMCallProfile(1, "generate_with_tools", 0.1, input_tokens=10, prompt_chars=100),
        LLMCallProfile(2, "generate_with_tools", 0.1, input_tokens=30, prompt_chars=300),
    )
    metrics = RealDeveloperTaskMetrics("A", "developer-1", 1.0, llm_calls=2, input_tokens=40, llm_profiles=profiles)
    result = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="profile",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=1.0,
        task_metrics=(metrics,),
    )

    assert result.max_prompt_chars_per_task == 300
    assert result.max_input_tokens_per_call == 30
    assert result.max_context_growth_ratio == 3.0


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
