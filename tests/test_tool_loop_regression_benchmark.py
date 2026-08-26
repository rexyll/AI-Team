import pytest

from benchmarks.tool_loop_regression import (
    SCENARIOS,
    ToolLoopBenchmarkMetrics,
    assert_correctness_preserved,
    compare_metrics,
)


def test_regression_corpus_is_fixed_and_covers_required_scenarios():
    assert SCENARIOS == (
        "serial",
        "partial",
        "independent",
        "long_tool_loop",
        "failure_recovery",
    )


def test_metric_comparison_reports_relative_changes():
    baseline = ToolLoopBenchmarkMetrics(1.0, 100, 200, 10_000, 50.0, 0.20, 0.10, 20_000)
    candidate = ToolLoopBenchmarkMetrics(1.0, 80, 150, 8_000, 40.0, 0.10, 0.05, 12_000)

    changes = compare_metrics(baseline, candidate)

    assert changes["llm_calls"] == pytest.approx(-0.20)
    assert changes["tool_calls"] == pytest.approx(-0.25)
    assert changes["input_tokens"] == pytest.approx(-0.20)
    assert changes["duration_seconds"] == pytest.approx(-0.20)
    assert changes["duplicate_ratio"] == pytest.approx(-0.50)


def test_correctness_guard_rejects_completion_regression():
    baseline = ToolLoopBenchmarkMetrics(1.0, 10, 20, 1000, 1.0, 0.1, 0.0, 100)
    candidate = ToolLoopBenchmarkMetrics(0.99, 8, 18, 800, 0.8, 0.05, 0.0, 80)

    with pytest.raises(AssertionError, match="completion rate"):
        assert_correctness_preserved(baseline, candidate)


def test_correctness_guard_allows_cost_reduction_when_completion_is_stable():
    baseline = ToolLoopBenchmarkMetrics(1.0, 10, 20, 1000, 1.0, 0.1, 0.0, 100)
    candidate = ToolLoopBenchmarkMetrics(1.0, 8, 18, 800, 0.8, 0.05, 0.0, 80)

    assert_correctness_preserved(baseline, candidate)
