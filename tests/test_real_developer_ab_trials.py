from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from benchmarks.real_developer import ab_trials_cli
from benchmarks.real_developer.ab import BenchmarkABComparison
from benchmarks.real_developer.ab_trials import BenchmarkABTrialSummary
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _result(*, duration: float, llm_calls: int, completed: int = 1, failed: int = 0, blocked: int = 0, input_tokens: int = 0, cache_hits: int = 0) -> RealDeveloperBenchmarkResult:
    task = RealDeveloperTaskMetrics(
        task_id="TASK-TRIAL",
        developer_id="developer-1",
        duration_seconds=duration,
        llm_calls=llm_calls,
        input_tokens=input_tokens,
        cache_hits=cache_hits,
        failed=failed > 0,
        failure_reason="failure" if failed > 0 else None,
    )
    return RealDeveloperBenchmarkResult(
        scenario="serial",
        developer_count=1,
        task_count=1,
        completed=completed,
        failed=failed,
        blocked=blocked,
        duration_seconds=duration,
        task_metrics=(task,),
    )


def _comparison(*, valid: bool, duration_delta: float, llm_delta: int = 0, input_delta: int = 0, cache_delta: int = 0) -> BenchmarkABComparison:
    baseline = _result(duration=10.0, llm_calls=10, input_tokens=100, cache_hits=0)
    candidate = _result(duration=10.0 + duration_delta, llm_calls=10 + llm_delta, input_tokens=100 + input_delta, cache_hits=cache_delta)
    if not valid:
        baseline = replace(baseline, failed=1, completed=0)
    return BenchmarkABComparison(baseline=baseline, candidate=candidate)


def test_summary_uses_only_valid_trials_for_medians() -> None:
    comparisons = (
        _comparison(valid=True, duration_delta=-2.0),
        _comparison(valid=False, duration_delta=-9.0),
        _comparison(valid=True, duration_delta=4.0),
    )

    summary = BenchmarkABTrialSummary.from_comparisons(comparisons)

    assert summary.trials == 3
    assert summary.valid_trials == 2
    assert summary.invalid_trials == 1
    assert summary.baseline_success_rate == 2 / 3
    assert summary.candidate_success_rate == 1.0
    assert summary.median_duration_change_ratio == 0.1
    assert summary.to_dict()["valid_sample_rate"] == 2 / 3
    assert summary.duration_improved_trials == 1
    assert summary.llm_calls_nonworse_trials == 2
    assert summary.input_tokens_nonworse_trials == 2
    assert summary.duplicate_execution_nonworse_trials == 2


def test_summary_has_none_for_performance_medians_when_all_trials_invalid() -> None:
    summary = BenchmarkABTrialSummary.from_comparisons(
        (_comparison(valid=False, duration_delta=-2.0),)
    )

    assert summary.valid_trials == 0
    assert summary.median_duration_change_ratio is None
    assert summary.to_dict()["median"]["duration_change_ratio"] is None
    assert summary.verdict == "insufficient_valid_samples"
    assert summary.duration_improved_trials == 0
    assert summary.llm_calls_nonworse_trials == 0
    assert summary.input_tokens_nonworse_trials == 0
    assert summary.duplicate_execution_nonworse_trials == 0


def test_summary_rejects_reliability_regression_before_efficiency_claim() -> None:
    comparisons = tuple(
        _comparison(valid=True, duration_delta=-2.0)
        for _ in range(4)
    ) + (
        _comparison(valid=False, duration_delta=-8.0),
    )
    baseline_failure = _result(duration=10.0, llm_calls=10)
    candidate_failure = _result(duration=9.0, llm_calls=8, completed=0, failed=1)
    comparisons = comparisons[:-1] + (BenchmarkABComparison(baseline=baseline_failure, candidate=candidate_failure),)

    summary = BenchmarkABTrialSummary.from_comparisons(comparisons)

    assert summary.statistically_ready is True
    assert summary.reliability_preserved is False
    assert summary.efficiency_improved is False
    assert summary.verdict == "reliability_regression"


def test_summary_marks_unambiguous_efficiency_improvement() -> None:
    comparisons = tuple(
        _comparison(valid=True, duration_delta=-2.0, llm_delta=-1, input_delta=-20)
        for _ in range(4)
    )

    summary = BenchmarkABTrialSummary.from_comparisons(comparisons)

    assert summary.statistically_ready is True
    assert summary.reliability_preserved is True
    assert summary.efficiency_improved is True
    assert summary.verdict == "efficiency_improved"
    assert summary.cache_effect_observed is False
    assert summary.duration_improved_trials == 4
    assert summary.llm_calls_nonworse_trials == 4
    assert summary.input_tokens_nonworse_trials == 4
    assert summary.duplicate_execution_nonworse_trials == 4


def test_summary_defaults_to_no_clear_gain_when_duration_improves_but_cost_rises() -> None:
    comparisons = tuple(
        _comparison(valid=True, duration_delta=-2.0, llm_delta=1, input_delta=10)
        for _ in range(4)
    )

    summary = BenchmarkABTrialSummary.from_comparisons(comparisons)

    assert summary.statistically_ready is True
    assert summary.reliability_preserved is True
    assert summary.efficiency_improved is False
    assert summary.verdict == "no_clear_efficiency_gain"
    assert summary.duration_improved_trials == 4
    assert summary.llm_calls_nonworse_trials == 0
    assert summary.input_tokens_nonworse_trials == 0


def test_cache_effect_is_observed_when_any_valid_trial_has_a_cache_hit() -> None:
    comparisons = (
        _comparison(valid=True, duration_delta=1.0, cache_delta=0),
        _comparison(valid=True, duration_delta=1.0, cache_delta=1),
        _comparison(valid=True, duration_delta=1.0, cache_delta=0),
        _comparison(valid=True, duration_delta=1.0, cache_delta=0),
    )

    summary = BenchmarkABTrialSummary.from_comparisons(comparisons)

    assert summary.median_cache_hits_delta == 0.0
    assert summary.cache_hit_observations == 1
    assert summary.cache_effect_observed is True


def test_to_dict_exposes_valid_trial_distribution_counts() -> None:
    summary = BenchmarkABTrialSummary.from_comparisons(
        (
            _comparison(valid=True, duration_delta=-1.0, llm_delta=-1, input_delta=-1),
            _comparison(valid=True, duration_delta=1.0, llm_delta=1, input_delta=1),
            _comparison(valid=True, duration_delta=-1.0, llm_delta=0, input_delta=0),
            _comparison(valid=True, duration_delta=-1.0, llm_delta=0, input_delta=0),
        )
    )

    payload = summary.to_dict()
    assert payload["valid_trial_counts"] == {
        "duration_improved": 3,
        "llm_calls_nonworse": 3,
        "input_tokens_nonworse": 3,
        "duplicate_execution_nonworse": 4,
        "cache_hit_observations": 0,
    }


def test_trials_cli_rejects_non_positive_trials() -> None:
    with patch.object(ab_trials_cli, "build_live_executor_factory"):
        try:
            ab_trials_cli.main(["--developers", "1", "--trials", "0"])
        except SystemExit as exc:
            assert exc.code == "--trials must be greater than 0"
        else:
            raise AssertionError("expected SystemExit")
