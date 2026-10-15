import pytest

from benchmarks.tool_loop_regression import (
    ToolLoopBenchmarkMetrics,
    ToolLoopRegressionCase,
    assert_regression_gate,
    build_regression_report,
)


def _metrics(llm_calls: int = 10) -> ToolLoopBenchmarkMetrics:
    return ToolLoopBenchmarkMetrics(
        completion_rate=1.0,
        llm_calls=llm_calls,
        tool_calls=4,
        input_tokens=100,
        duration_seconds=10.0,
        duplicate_ratio=0.0,
        retry_ratio=0.0,
        tool_result_chars=1000,
    )


def _report(llm_delta: int = 1):
    cases = {
        scenario: ToolLoopRegressionCase(
            scenario=scenario,
            baseline=_metrics(10),
            candidate=_metrics(10 + llm_delta),
        )
        for scenario in ("serial", "partial", "independent", "long_tool_loop", "failure_recovery")
    }
    return build_regression_report(cases)


def test_regression_gate_default_preserves_zero_increase_policy():
    with pytest.raises(AssertionError, match="llm_calls increased"):
        assert_regression_gate(_report())


def test_regression_gate_accepts_explicit_measurement_tolerance():
    report = _report()
    assert_regression_gate(report, max_cost_increase=0.10)


def test_regression_gate_rejects_invalid_tolerance():
    report = _report(0)
    with pytest.raises(ValueError):
        assert_regression_gate(report, max_cost_increase=-0.01)
    with pytest.raises(TypeError):
        assert_regression_gate(report, max_cost_increase=True)
