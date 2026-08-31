from benchmarks.real_developer.ab import BenchmarkABComparison
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _result(*, tool_calls: int, exact_duplicates: int, cache_hits: int, llm_calls: int, duration: float) -> RealDeveloperBenchmarkResult:
    telemetry = tuple(
        {"category": "exact_duplicate" if index < exact_duplicates else "exploration"}
        for index in range(tool_calls)
    )
    task = RealDeveloperTaskMetrics(
        task_id="TASK-AB-001",
        developer_id="developer-1",
        duration_seconds=duration,
        llm_calls=llm_calls,
        input_tokens=100,
        output_tokens=20,
        llm_latency_seconds=duration * 0.8,
        tool_calls=tool_calls,
        unique_tool_calls=tool_calls - exact_duplicates,
        duplicate_tool_calls=exact_duplicates,
        retry_tool_calls=0,
        cache_hits=cache_hits,
        cache_misses=max(0, tool_calls - cache_hits),
        tool_result_chars=1000,
        tool_loop_telemetry=telemetry,
        developer_decision_trace=(
            {"convergence_reason": "new_evidence_requires_reasoning"},
        ) * llm_calls,
    )
    return RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=duration,
        task_metrics=(task,),
    )


def test_ab_comparison_exposes_efficiency_deltas_and_decision_reasons() -> None:
    baseline = _result(tool_calls=5, exact_duplicates=0, cache_hits=0, llm_calls=4, duration=10.0)
    candidate = _result(tool_calls=5, exact_duplicates=2, cache_hits=2, llm_calls=3, duration=8.0)

    comparison = BenchmarkABComparison(baseline=baseline, candidate=candidate)

    assert comparison.llm_calls_delta == -1
    assert comparison.llm_call_change_ratio == -0.25
    assert comparison.duration_delta == -2.0
    assert comparison.exact_duplicate_tool_calls_delta == 2
    assert comparison.cache_probe_excess_delta == 0
    assert comparison.decision_trace_delta == -1
    assert comparison.correctness_preserved is True

    payload = comparison.to_dict()
    assert payload["delta"]["exact_duplicate_tool_calls"] == 2
    assert payload["delta"]["decision_trace_count"] == -1
    assert payload["delta"]["decision_reason_counts"]["candidate"]["new_evidence_requires_reasoning"] == 3


def test_ab_comparison_detects_cache_probe_excess_from_candidate_telemetry() -> None:
    baseline = _result(tool_calls=4, exact_duplicates=0, cache_hits=0, llm_calls=2, duration=5.0)
    candidate = _result(tool_calls=4, exact_duplicates=1, cache_hits=3, llm_calls=2, duration=5.0)

    comparison = BenchmarkABComparison(baseline=baseline, candidate=candidate)

    assert comparison.cache_probe_excess_delta == 2
    assert comparison.sample_valid is True


def test_ab_comparison_does_not_call_failed_retry_a_correctness_improvement() -> None:
    baseline = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=5.0,
        task_metrics=(
            RealDeveloperTaskMetrics(
                task_id="TASK-AB-002",
                developer_id="developer-1",
                duration_seconds=5.0,
                tool_calls=2,
                unique_tool_calls=1,
                duplicate_tool_calls=1,
                retry_tool_calls=1,
                tool_loop_telemetry=(
                    {"category": "failure_recovery"},
                    {"category": "exploration"},
                ),
            ),
        ),
    )
    candidate = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=1,
        failed=0,
        blocked=0,
        duration_seconds=5.0,
        task_metrics=(
            RealDeveloperTaskMetrics(
                task_id="TASK-AB-002",
                developer_id="developer-1",
                duration_seconds=5.0,
                tool_calls=2,
                unique_tool_calls=1,
                duplicate_tool_calls=1,
                retry_tool_calls=1,
                tool_loop_telemetry=(
                    {"category": "failure_recovery"},
                    {"category": "exploration"},
                ),
            ),
        ),
    )

    comparison = BenchmarkABComparison(baseline=baseline, candidate=candidate)

    assert comparison.exact_duplicate_tool_calls_delta == 0
    assert comparison.correctness_preserved is True
