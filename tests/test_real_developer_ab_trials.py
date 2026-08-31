from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from benchmarks.real_developer import ab_trials_cli
from benchmarks.real_developer.ab import BenchmarkABComparison
from benchmarks.real_developer.ab_trials import BenchmarkABTrialSummary
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


def _result(*, duration: float, llm_calls: int, completed: int = 1, failed: int = 0, blocked: int = 0) -> RealDeveloperBenchmarkResult:
    task = RealDeveloperTaskMetrics(
        task_id="TASK-TRIAL",
        developer_id="developer-1",
        duration_seconds=duration,
        llm_calls=llm_calls,
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


def _comparison(*, valid: bool, duration_delta: float) -> BenchmarkABComparison:
    baseline = _result(duration=10.0, llm_calls=2)
    candidate = _result(duration=10.0 + duration_delta, llm_calls=2)
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


def test_summary_has_none_for_performance_medians_when_all_trials_invalid() -> None:
    summary = BenchmarkABTrialSummary.from_comparisons(
        (_comparison(valid=False, duration_delta=-2.0),)
    )

    assert summary.valid_trials == 0
    assert summary.median_duration_change_ratio is None
    assert summary.to_dict()["median"]["duration_change_ratio"] is None


def test_trials_cli_rejects_non_positive_trials() -> None:
    with patch.object(ab_trials_cli, "build_live_executor_factory"):
        try:
            ab_trials_cli.main(["--developers", "1", "--trials", "0"])
        except SystemExit as exc:
            assert exc.code == "--trials must be greater than 0"
        else:
            raise AssertionError("expected SystemExit")
