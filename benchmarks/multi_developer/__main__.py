from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from time import sleep

from runtime.task_manager import TaskManager

from .report import BenchmarkReport
from .runner import MultiDeveloperBenchmark
from .scenarios import fully_parallel_tasks, partially_parallel_tasks, serial_tasks

SCENARIOS = {
    "fully-parallel": fully_parallel_tasks,
    "partially-parallel": partially_parallel_tasks,
    "serial": serial_tasks,
}


class _DeterministicBenchmarkExecutor:
    """Deterministic executor used by the CLI to isolate scheduler performance.

    It intentionally avoids model/provider calls. ``delay`` represents a
    synthetic unit of task work so parallel speedup can be observed without
    network or LLM latency dominating the measurement.
    """

    def __init__(self, manager: TaskManager, developer_count: int, delay: float) -> None:
        self.manager = manager
        self.developer_count = developer_count
        self.delay = delay

    def run_until_idle(self) -> None:
        while True:
            self.manager.get_ready_tasks()
            ready = [
                task
                for task in self.manager.get_all_tasks()
                if task.status == "ready"
                and all(
                    self.manager.get_task(dep).status == "completed"
                    for dep in task.dependencies
                )
            ]
            if not ready:
                return

            def execute(task_id: str) -> None:
                self.manager.mark_running(task_id)
                if self.delay:
                    sleep(self.delay)
                self.manager.mark_completed(task_id, result={"benchmark": "deterministic"})

            with ThreadPoolExecutor(max_workers=self.developer_count) as pool:
                futures = [pool.submit(execute, task.id) for task in ready]
                for future in futures:
                    future.result()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic AI-Team multi-Developer benchmarks."
    )
    parser.add_argument(
        "--developers",
        type=int,
        nargs="+",
        default=[1],
        help="Developer counts to benchmark (default: 1).",
    )
    parser.add_argument(
        "--scenario",
        choices=tuple(SCENARIOS),
        default="fully-parallel",
        help="Benchmark scenario to run (default: fully-parallel).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.02,
        help="Synthetic task duration in seconds (default: 0.02).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if any(count <= 0 for count in args.developers):
        parser.error("--developers values must be greater than 0")
    if args.delay < 0:
        parser.error("--delay must be greater than or equal to 0")

    scenario_factory = SCENARIOS[args.scenario]
    benchmark = MultiDeveloperBenchmark(
        scenario_factory=scenario_factory,
        executor_factory=lambda manager, count: _DeterministicBenchmarkExecutor(
            manager, count, args.delay
        ),
        scenario_name=args.scenario,
    )

    results = tuple(benchmark.run(count) for count in args.developers)
    report = BenchmarkReport.from_results(results)
    print(report.render_table())

    if 1 in args.developers and len(args.developers) > 1:
        measured = report.with_baseline(1)
        if measured:
            print("\nBaseline comparison:")
            for result in measured:
                print(
                    f"{result.result.scenario} / {result.result.developer_count} Dev: "
                    f"speedup={result.speedup:.3f}x, "
                    f"efficiency={result.parallel_efficiency:.3f}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
