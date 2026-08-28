from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


SCENARIOS = (
    "serial",
    "partial",
    "independent",
    "long_tool_loop",
    "failure_recovery",
)


@dataclass(frozen=True)
class ToolLoopBenchmarkMetrics:
    """Stable metric surface used by the Tool Loop regression corpus."""

    completion_rate: float
    llm_calls: int
    tool_calls: int
    input_tokens: int
    duration_seconds: float
    duplicate_ratio: float
    retry_ratio: float
    tool_result_chars: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.completion_rate <= 1.0:
            raise ValueError("completion_rate must be between 0 and 1")
        for name in ("llm_calls", "tool_calls", "input_tokens", "tool_result_chars"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be >= 0")
        for name in ("duplicate_ratio", "retry_ratio"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class ToolLoopRegressionCase:
    """Baseline/candidate pair for one named regression scenario."""

    scenario: str
    baseline: ToolLoopBenchmarkMetrics
    candidate: ToolLoopBenchmarkMetrics

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"unsupported tool-loop scenario: {self.scenario}")


@dataclass(frozen=True)
class ToolLoopRegressionReport:
    """Comparable results for the complete fixed regression corpus."""

    changes: Mapping[str, dict[str, float]]

    @property
    def scenarios(self) -> tuple[str, ...]:
        return tuple(self.changes.keys())


def compare_metrics(
    baseline: ToolLoopBenchmarkMetrics,
    candidate: ToolLoopBenchmarkMetrics,
) -> dict[str, float]:
    """Return percentage change for metrics where a relative change is defined."""

    def change(before: float, after: float) -> float:
        if before == 0:
            return 0.0 if after == 0 else float("inf")
        return (after - before) / before

    return {
        "completion_rate": change(baseline.completion_rate, candidate.completion_rate),
        "llm_calls": change(baseline.llm_calls, candidate.llm_calls),
        "tool_calls": change(baseline.tool_calls, candidate.tool_calls),
        "input_tokens": change(baseline.input_tokens, candidate.input_tokens),
        "duration_seconds": change(baseline.duration_seconds, candidate.duration_seconds),
        "duplicate_ratio": change(baseline.duplicate_ratio, candidate.duplicate_ratio),
        "retry_ratio": change(baseline.retry_ratio, candidate.retry_ratio),
        "tool_result_chars": change(baseline.tool_result_chars, candidate.tool_result_chars),
    }


def assert_correctness_preserved(
    baseline: ToolLoopBenchmarkMetrics,
    candidate: ToolLoopBenchmarkMetrics,
) -> None:
    """Raise if a candidate benchmark regresses completion correctness."""
    if candidate.completion_rate < baseline.completion_rate:
        raise AssertionError(
            "tool-loop optimization reduced completion rate: "
            f"{baseline.completion_rate:.3f} -> {candidate.completion_rate:.3f}"
        )


def build_regression_report(
    cases: Mapping[str, ToolLoopRegressionCase],
) -> ToolLoopRegressionReport:
    """Build a report only when the fixed corpus is complete and unambiguous."""
    expected = set(SCENARIOS)
    actual = set(cases)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise AssertionError("tool-loop regression corpus mismatch: " + "; ".join(details))

    changes: dict[str, dict[str, float]] = {}
    for scenario in SCENARIOS:
        case = cases[scenario]
        if case.scenario != scenario:
            raise AssertionError(
                f"tool-loop regression case key mismatch: key={scenario}, case={case.scenario}"
            )
        assert_correctness_preserved(case.baseline, case.candidate)
        changes[scenario] = compare_metrics(case.baseline, case.candidate)
    return ToolLoopRegressionReport(changes=changes)


def assert_regression_gate(report: ToolLoopRegressionReport) -> None:
    """Enforce the release gate: correctness stable and no cost regression.

    Cost metrics are intentionally limited to the optimization targets of
    Phase 10.7. Duplicate/retry ratios may trade off independently and are
    therefore reported but not hard-gated here.
    """
    gated_metrics = (
        "llm_calls",
        "tool_calls",
        "input_tokens",
        "duration_seconds",
        "tool_result_chars",
    )
    failures: list[str] = []
    for scenario, changes in report.changes.items():
        for metric in gated_metrics:
            if changes[metric] > 0:
                failures.append(f"{scenario}:{metric} increased by {changes[metric]:.3f}")
    if failures:
        raise AssertionError("tool-loop regression gate failed: " + "; ".join(failures))
