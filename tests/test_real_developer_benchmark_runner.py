from benchmarks.real_developer.runner import RealDeveloperBenchmark
from benchmarks.real_developer.scenarios import independent_implementation_tasks
from benchmarks.real_developer.metrics import RealDeveloperTaskMetrics


class _DeterministicDeveloperExecutor:
    def __init__(self, manager, developer_count):
        self.manager = manager
        self.developer_count = developer_count

    def run_task(self, task, developer_id):
        self.manager.mark_running(task.id)
        self.manager.mark_completed(task.id, result={"benchmark": "instrumented"})
        return RealDeveloperTaskMetrics(
            task_id=task.id,
            developer_id=developer_id,
            duration_seconds=0.01,
            llm_calls=1,
            input_tokens=10,
            output_tokens=5,
        )


def test_real_developer_benchmark_collects_instrumentation():
    benchmark = RealDeveloperBenchmark(
        scenario_factory=independent_implementation_tasks,
        executor_factory=_DeterministicDeveloperExecutor,
        scenario_name="independent",
    )

    result = benchmark.run(2)

    assert result.completed == 4
    assert result.failed == 0
    assert result.blocked == 0
    assert result.llm_calls == 4
    assert result.total_tokens == 60
