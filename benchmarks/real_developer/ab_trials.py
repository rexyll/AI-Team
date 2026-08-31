from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

from .ab import BenchmarkABComparison


MIN_RECOMMENDED_VALID_TRIALS = 3
MIN_RECOMMENDED_VALID_SAMPLE_RATE = 0.8


@dataclass(frozen=True)
class BenchmarkABTrialSummary:
    """Aggregate valid paired A/B trials and expose conservative verdict signals."""

    trials: int
    valid_trials: int
    invalid_trials: int
    baseline_success_rate: float
    candidate_success_rate: float
    median_duration_change_ratio: float | None
    median_llm_call_change_ratio: float | None
    median_input_token_change_ratio: float | None
    median_exact_duplicate_tool_calls_delta: float | None
    median_duplicate_execution_tool_calls_delta: float | None
    median_cache_hits_delta: float | None
    median_decision_trace_delta: float | None

    @classmethod
    def from_comparisons(cls, comparisons: Iterable[BenchmarkABComparison]) -> "BenchmarkABTrialSummary":
        items = tuple(comparisons)
        valid = tuple(item for item in items if item.sample_valid)
        baseline_successes = sum(
            item.baseline.failed == 0
            and item.baseline.blocked == 0
            and item.baseline.completed == item.baseline.task_count
            for item in items
        )
        candidate_successes = sum(
            item.candidate.failed == 0
            and item.candidate.blocked == 0
            and item.candidate.completed == item.candidate.task_count
            for item in items
        )

        def med(values: Iterable[float]) -> float | None:
            values = tuple(values)
            return float(median(values)) if values else None

        return cls(
            trials=len(items),
            valid_trials=len(valid),
            invalid_trials=len(items) - len(valid),
            baseline_success_rate=(baseline_successes / len(items)) if items else 0.0,
            candidate_success_rate=(candidate_successes / len(items)) if items else 0.0,
            median_duration_change_ratio=med(item.duration_change_ratio for item in valid),
            median_llm_call_change_ratio=med(item.llm_call_change_ratio for item in valid),
            median_input_token_change_ratio=med(item.input_token_change_ratio for item in valid),
            median_exact_duplicate_tool_calls_delta=med(float(item.exact_duplicate_tool_calls_delta) for item in valid),
            median_duplicate_execution_tool_calls_delta=med(float(item.duplicate_execution_tool_calls_delta) for item in valid),
            median_cache_hits_delta=med(float(item.candidate.cache_hits - item.baseline.cache_hits) for item in valid),
            median_decision_trace_delta=med(float(item.decision_trace_delta) for item in valid),
        )

    @property
    def valid_sample_rate(self) -> float:
        return self.valid_trials / self.trials if self.trials else 0.0

    @property
    def reliability_preserved(self) -> bool:
        """Conservative reliability check across all requested paired trials."""
        return self.candidate_success_rate >= self.baseline_success_rate

    @property
    def statistically_ready(self) -> bool:
        """Whether enough valid paired trials exist for an efficiency conclusion."""
        return (
            self.valid_trials >= MIN_RECOMMENDED_VALID_TRIALS
            and self.valid_sample_rate >= MIN_RECOMMENDED_VALID_SAMPLE_RATE
        )

    @property
    def efficiency_improved(self) -> bool | None:
        """Whether the median valid-trial profile shows an unambiguous improvement."""
        if self.median_duration_change_ratio is None:
            return None
        return (
            self.reliability_preserved
            and self.median_duration_change_ratio < 0
            and (self.median_llm_call_change_ratio or 0.0) <= 0
            and (self.median_input_token_change_ratio or 0.0) <= 0
            and (self.median_duplicate_execution_tool_calls_delta or 0.0) <= 0
        )

    @property
    def cache_effect_observed(self) -> bool:
        """Whether valid live trials observed at least one additional cache hit."""
        return (self.median_cache_hits_delta or 0.0) > 0

    @property
    def verdict(self) -> str:
        """Return a conservative experiment conclusion."""
        if not self.statistically_ready:
            return "insufficient_valid_samples"
        if not self.reliability_preserved:
            return "reliability_regression"
        if self.efficiency_improved is True:
            return "efficiency_improved"
        return "no_clear_efficiency_gain"

    def to_dict(self) -> dict[str, object]:
        return {
            "trials": self.trials,
            "valid_trials": self.valid_trials,
            "invalid_trials": self.invalid_trials,
            "valid_sample_rate": self.valid_sample_rate,
            "baseline_success_rate": self.baseline_success_rate,
            "candidate_success_rate": self.candidate_success_rate,
            "statistically_ready": self.statistically_ready,
            "reliability_preserved": self.reliability_preserved,
            "efficiency_improved": self.efficiency_improved,
            "cache_effect_observed": self.cache_effect_observed,
            "verdict": self.verdict,
            "median": {
                "duration_change_ratio": self.median_duration_change_ratio,
                "llm_call_change_ratio": self.median_llm_call_change_ratio,
                "input_token_change_ratio": self.median_input_token_change_ratio,
                "exact_duplicate_tool_calls_delta": self.median_exact_duplicate_tool_calls_delta,
                "duplicate_execution_tool_calls_delta": self.median_duplicate_execution_tool_calls_delta,
                "cache_hits_delta": self.median_cache_hits_delta,
                "decision_trace_delta": self.median_decision_trace_delta,
            },
        }
