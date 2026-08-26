from __future__ import annotations

import argparse

from .live import build_live_executor_factory
from .runner import RealDeveloperBenchmark
from .scenarios import (
    independent_implementation_tasks,
    partial_implementation_tasks,
    serial_implementation_tasks,
)

SCENARIOS = {
    "independent": independent_implementation_tasks,
    "partial": partial_implementation_tasks,
    "serial": serial_implementation_tasks,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Real Developer benchmarks. Live provider calls require --live."
    )
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

    executor_factory = build_live_executor_factory(
        provider_profile=args.provider,
        model=args.model,
    )
    for developer_count in args.developers:
        durations: list[float] = []
        for _ in range(args.repeat):
            benchmark = RealDeveloperBenchmark(
                scenario_factory=SCENARIOS[args.scenario],
                executor_factory=executor_factory,
                scenario_name=args.scenario,
            )
            result = benchmark.run(developer_count)
            durations.append(result.duration_seconds)
            print(
                f"scenario={result.scenario} developers={result.developer_count} "
                f"tasks={result.task_count} completed={result.completed} "
                f"failed={result.failed} blocked={result.blocked} "
                f"duration_s={result.duration_seconds:.3f} "
                f"llm_calls={result.llm_calls} input_tokens={result.input_tokens} "
                f"output_tokens={result.output_tokens} "
                f"utilization={result.developer_utilization:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
