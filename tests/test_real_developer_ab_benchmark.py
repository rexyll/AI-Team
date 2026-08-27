from benchmarks.real_developer.ab import BenchmarkABComparison, RealDeveloperABBenchmark
from benchmarks.real_developer.metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics
from runtime.task import Task


class _FakeExecutor:
    def __init__(self, marker: str, manager):
        self.marker = marker
        self.manager = manager

    def run_task(self, task, developer_id):
        # The real DeveloperExecutor owns task lifecycle completion. Keep the
        # fake faithful to that contract so the A/B harness can classify this
        # deterministic sample as valid rather than leaving the task pending.
        self.manager.mark_developer_completed(task.id)
        return RealDeveloperTaskMetrics(
            task_id=task.id,
            developer_id=developer_id,
            duration_seconds=0.01,
            llm_calls=2,
            input_tokens=100 if self.marker == "baseline" else 40,
            output_tokens=10,
            tool_calls=2,
            unique_tool_calls=1,
            duplicate_tool_calls=1,
            tool_result_chars=1000 if self.marker == "baseline" else 100,
            cache_hits=0 if self.marker == "baseline" else 1,
            cache_misses=0 if self.marker == "baseline" else 1,
            llm_profiles=(),
        )


def _tasks():
    return [
        Task(
            id="TASK-AB-001",
            title="AB",
            description="benchmark",
            role="developer",
            status="pending",
        )
    ]


def test_ab_comparison_reports_candidate_token_reduction():
    calls = []

    def executor_factory(manager, count):
        marker = "baseline" if len(calls) == 0 else "candidate"
        calls.append(marker)
        return _FakeExecutor(marker, manager)

    result = RealDeveloperABBenchmark(
        scenario_factory=_tasks,
        executor_factory=executor_factory,
        scenario_name="cache-evidence",
    ).run(1)

    assert result.baseline.scenario.endswith("-baseline")
    assert result.candidate.scenario.endswith("-candidate")
    assert result.input_token_delta == -60
    assert result.input_token_change_ratio == -0.6
    assert result.tool_result_chars_delta == -900
    assert result.correctness_preserved
    assert result.sample_valid
    assert calls == ["baseline", "candidate"]


def test_ab_comparison_serializes_baseline_candidate_deltas_and_validity():
    metric = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="s",
        developer_count=1,
        task_count=0,
        completed=0,
        failed=0,
        blocked=0,
        duration_seconds=0,
        task_metrics=(),
    )
    comparison = BenchmarkABComparison(metric, metric)

    payload = comparison.to_dict()

    assert set(payload) == {"baseline", "candidate", "delta", "correctness_preserved", "sample_valid"}
    assert payload["correctness_preserved"] is True
    assert payload["sample_valid"] is True
    assert payload["delta"]["input_tokens"] == 0


def test_ab_comparison_marks_failed_samples_invalid():
    failed = RealDeveloperBenchmarkResult.from_task_metrics(
        scenario="s",
        developer_count=1,
        task_count=1,
        completed=0,
        failed=1,
        blocked=0,
        duration_seconds=0,
        task_metrics=(),
    )
    comparison = BenchmarkABComparison(failed, failed)

    assert comparison.sample_valid is False
