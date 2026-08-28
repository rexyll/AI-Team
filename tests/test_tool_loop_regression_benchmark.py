import pytest

from benchmarks.tool_loop_regression import (
    SCENARIOS,
    ToolLoopBenchmarkMetrics,
    ToolLoopRegressionCase,
    assert_correctness_preserved,
    assert_regression_gate,
    build_regression_report,
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


def _metrics(*, llm_calls=8, tool_calls=12, input_tokens=800, duration=4.0, results=800):
    return ToolLoopBenchmarkMetrics(1.0, llm_calls, tool_calls, input_tokens, duration, 0.1, 0.05, results)


def test_build_regression_report_requires_the_complete_fixed_corpus():
    case = ToolLoopRegressionCase("serial", _metrics(), _metrics(llm_calls=7))
    with pytest.raises(AssertionError, match="corpus mismatch"):
        build_regression_report({"serial": case})


def test_regression_gate_accepts_complete_cost_reduction():
    cases = {
        scenario: ToolLoopRegressionCase(scenario, _metrics(), _metrics(llm_calls=7, tool_calls=11, input_tokens=700, duration=3.5, results=700))
        for scenario in SCENARIOS
    }
    report = build_regression_report(cases)
    assert report.scenarios == SCENARIOS
    assert_regression_gate(report)


def test_regression_gate_rejects_any_gated_cost_increase():
    cases = {
        scenario: ToolLoopRegressionCase(scenario, _metrics(), _metrics(llm_calls=9))
        for scenario in SCENARIOS
    }
    report = build_regression_report(cases)
    with pytest.raises(AssertionError, match="regression gate failed"):
        assert_regression_gate(report)


def test_regression_gate_still_rejects_completion_regression():
    cases = {
        scenario: ToolLoopRegressionCase(scenario, _metrics(), ToolLoopBenchmarkMetrics(0.9, 7, 11, 700, 3.5, 0.1, 0.05, 700))
        for scenario in SCENARIOS
    }
    with pytest.raises(AssertionError, match="completion rate"):
        build_regression_report(cases)
