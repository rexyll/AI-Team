from __future__ import annotations

from unittest.mock import patch

from benchmarks.real_developer import ab_cli
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult


def _result(*, failed: int = 0, blocked: int = 0, completed: int = 1, task_count: int = 1) -> RealDeveloperBenchmarkResult:
    return RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="serial",
        developer_count=1,
        task_count=task_count,
        completed=completed,
        failed=failed,
        blocked=blocked,
        duration_seconds=1.0,
        task_metrics=(),
    )


class _Comparison:
    def __init__(self, *, valid: bool) -> None:
        self.sample_valid = valid
        self.correctness_preserved = True
        self.baseline = _result()
        self.candidate = _result()
        self.llm_calls_delta = 0
        self.llm_call_change_ratio = 0.0
        self.duration_delta = 0.0
        self.duration_change_ratio = 0.0
        self.input_token_delta = 0
        self.input_token_change_ratio = 0.0
        self.exact_duplicate_tool_calls_delta = 0
        self.cache_probe_excess_delta = 0
        self.decision_trace_delta = 0
        self.tool_result_chars_delta = 0
        self.duplicate_tool_calls_delta = 0

    def to_dict(self):
        return {"sample_valid": self.sample_valid}

    @staticmethod
    def _cache_probe_excess(_result):
        return 0


def test_strict_cli_rejects_invalid_samples() -> None:
    invalid = _Comparison(valid=False)

    class _Benchmark:
        def __init__(self, **_kwargs):
            pass

        def run(self, _count):
            return invalid

    with patch.object(ab_cli, "RealDeveloperABBenchmark", _Benchmark), patch.object(
        ab_cli, "build_live_executor_factory", lambda **_kwargs: object()
    ):
        assert ab_cli.main(["--developers", "1", "--require-valid-sample", "--json"]) == 2


def test_non_strict_cli_preserves_zero_exit_for_invalid_samples() -> None:
    invalid = _Comparison(valid=False)

    class _Benchmark:
        def __init__(self, **_kwargs):
            pass

        def run(self, _count):
            return invalid

    with patch.object(ab_cli, "RealDeveloperABBenchmark", _Benchmark), patch.object(
        ab_cli, "build_live_executor_factory", lambda **_kwargs: object()
    ):
        assert ab_cli.main(["--developers", "1", "--json"]) == 0
