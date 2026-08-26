from __future__ import annotations

import argparse

from .live import build_live_executor_factory
from .runner import RealDeveloperBenchmark
from .scenarios import independent_implementation_tasks, partial_implementation_tasks, serial_implementation_tasks

SCENARIOS = {"independent": independent_implementation_tasks, "partial": partial_implementation_tasks, "serial": serial_implementation_tasks}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Real Developer benchmarks. Live provider calls require --live.")
    parser.add_argument("--developers", type=int, nargs="+", default=[1])
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), default="independent")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--live", action="store_true", help="Allow real provider/API calls.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if any(count <= 0 for count in args.developers):
        raise SystemExit("--developers values must be greater than 0")
    if args.repeat <= 0:
        raise SystemExit("--repeat must be greater than 0")
    if not args.live:
        raise SystemExit("Real Developer benchmark requires explicit --live")

    executor_factory = build_live_executor_factory(provider_profile=args.provider, model=args.model)
    for developer_count in args.developers:
        results = []
        for _ in range(args.repeat):
            result = RealDeveloperBenchmark(
                scenario_factory=SCENARIOS[args.scenario],
                executor_factory=executor_factory,
                scenario_name=args.scenario,
            ).run(developer_count)
            results.append(result)
            print(
                f"scenario={result.scenario} developers={result.developer_count} tasks={result.task_count} "
                f"completed={result.completed} failed={result.failed} blocked={result.blocked} "
                f"duration_s={result.duration_seconds:.3f} llm_calls={result.llm_calls} "
                f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} "
                f"tool_calls={result.tool_calls} test_commands={result.test_commands} "
                f"avg_llm_latency_s={result.avg_llm_latency_seconds:.3f} llm_time_ratio={result.llm_time_ratio:.3f} "
                f"utilization={result.developer_utilization:.3f}"
            )
            for metric in result.task_metrics:
                print(
                    f"  task={metric.task_id} developer={metric.developer_id} duration_s={metric.duration_seconds:.3f} "
                    f"llm_calls={metric.llm_calls} input_tokens={metric.input_tokens} output_tokens={metric.output_tokens} "
                    f"tool_calls={metric.tool_calls} test_commands={metric.test_commands} failed={metric.failed}"
                )
        if len(results) > 1:
            mean_duration = sum(item.duration_seconds for item in results) / len(results)
            mean_calls = sum(item.llm_calls for item in results) / len(results)
            mean_tokens = sum(item.total_tokens for item in results) / len(results)
            print(f"aggregate developers={developer_count} runs={len(results)} mean_duration_s={mean_duration:.3f} mean_llm_calls={mean_calls:.1f} mean_total_tokens={mean_tokens:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
