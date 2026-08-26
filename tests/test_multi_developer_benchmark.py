from benchmarks.multi_developer.runner import MultiDeveloperBenchmark
from benchmarks.multi_developer.scenarios import (
    fully_parallel_tasks,
    partially_parallel_tasks,
    serial_tasks,
)
from runtime.task_manager import TaskManager


class _DeterministicExecutor:
    def __init__(self, manager: TaskManager, developer_count: int):
        self.manager = manager
        self.developer_count = developer_count

    def run_until_idle(self):
        # The benchmark contract is tested independently of real model calls.
        # Mark currently runnable work completed in deterministic rounds.
        while True:
            ready = [
                task
                for task in self.manager.get_all_tasks()
                if task.status in {"pending", "ready"}
                and all(
                    self.manager.get_task(dep).status == "completed"
                    for dep in task.dependencies
                )
            ]
            if not ready:
                return
            for task in ready:
                self.manager.mark_running(task.id)
                self.manager.mark_completed(
                    task.id,
                    result={"developer_count": self.developer_count},
                )


def _executor_factory(manager, developer_count):
    return _DeterministicExecutor(manager, developer_count)


def test_standard_scenarios_have_expected_dependency_shapes():
    assert [task.id for task in fully_parallel_tasks()] == [
        "ROOT", "TASK-1", "TASK-2", "TASK-3", "TASK-4"
    ]
    assert partially_parallel_tasks()[-1].dependencies == ["TASK-A", "TASK-B", "TASK-C"]
    serial = serial_tasks()
    assert serial[-1].dependencies == ["TASK-4"]


def test_benchmark_runner_reports_task_outcomes():
    benchmark = MultiDeveloperBenchmark(
        scenario_factory=fully_parallel_tasks,
        executor_factory=_executor_factory,
        scenario_name="fully-parallel",
    )

    result = benchmark.run(3)

    assert result.scenario == "fully-parallel"
    assert result.developer_count == 3
    assert result.task_count == 5
    assert result.completed == 5
    assert result.failed == 0
    assert result.blocked == 0
    assert result.duration_seconds >= 0


def test_benchmark_runner_normalizes_pending_root_to_ready():
    observed = {}

    def executor_factory(manager, developer_count):
        observed["root_status"] = manager.get_task("ROOT").status
        return _DeterministicExecutor(manager, developer_count)

    benchmark = MultiDeveloperBenchmark(
        scenario_factory=lambda: [
            # Deliberately start ROOT as pending; the benchmark runner owns
            # scenario lifecycle normalization before executor construction.
            __import__("runtime.task", fromlist=["Task"]).Task(
                "ROOT", "Root", "root", "developer"
            ),
            __import__("runtime.task", fromlist=["Task"]).Task(
                "CHILD", "Child", "child", "developer", dependencies=["ROOT"]
            ),
        ],
        executor_factory=executor_factory,
        scenario_name="pending-root",
    )

    result = benchmark.run(1)

    assert observed["root_status"] == "ready"
    assert result.completed == 2


def test_benchmark_baseline_calculates_speedup_and_efficiency():
    benchmark = MultiDeveloperBenchmark(
        scenario_factory=fully_parallel_tasks,
        executor_factory=_executor_factory,
        scenario_name="fully-parallel",
    )
    baseline = benchmark.run(1)
    result = benchmark.run(2)

    measured = result.with_baseline(baseline)

    assert measured.speedup > 0
    assert measured.parallel_efficiency > 0
    assert measured.to_dict()["developer_count"] == 2


def test_benchmark_rejects_invalid_developer_count():
    benchmark = MultiDeveloperBenchmark(
        scenario_factory=serial_tasks,
        executor_factory=_executor_factory,
        scenario_name="serial",
    )

    for value in (0, -1):
        try:
            benchmark.run(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid developer count must be rejected")
