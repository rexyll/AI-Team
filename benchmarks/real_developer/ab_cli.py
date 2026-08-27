from __future__ import annotations

import argparse
import json

from .ab import RealDeveloperABBenchmark
from .live import build_live_executor_factory
from .scenarios import independent_implementation_tasks, partial_implementation_tasks, serial_implementation_tasks

SCENARIOS = {
    "independent": independent_implementation_tasks,
    "partial": partial_implementation_tasks,
    "serial": serial_implementation_tasks,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a live baseline/candidate Developer A/B benchmark.")
    parser.add_argument("--developers", type=int, nargs="+", default=[1])
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), default="serial")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if any(count <= 0 for count in args.developers):
        raise SystemExit("--developers values must be greater than 0")

    executor_factory = build_live_executor_factory(provider_profile=args.provider, model=args.model)
    for developer_count in args.developers:
        comparison = RealDeveloperABBenchmark(
            scenario_factory=SCENARIOS[args.scenario],
            executor_factory=executor_factory,
            scenario_name=args.scenario,
        ).run(developer_count)
        payload = comparison.to_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            baseline = comparison.baseline
            candidate = comparison.candidate
            print(
                f"scenario={args.scenario} developers={developer_count} "
                f"baseline_input_tokens={baseline.input_tokens} candidate_input_tokens={candidate.input_tokens} "
                f"input_token_delta={comparison.input_token_delta} "
                f"input_token_change_ratio={comparison.input_token_change_ratio:.4f}"
            )
            print(
                f"baseline_context_growth={baseline.max_context_growth_ratio:.3f} "
                f"candidate_context_growth={candidate.max_context_growth_ratio:.3f} "
                f"context_growth_delta={comparison.max_context_growth_delta:.3f}"
            )
            print(
                f"baseline_tool_result_chars={baseline.tool_result_chars} "
                f"candidate_tool_result_chars={candidate.tool_result_chars} "
                f"tool_result_chars_delta={comparison.tool_result_chars_delta}"
            )
            print(
                f"baseline_duplicate_tool_calls={baseline.duplicate_tool_calls} "
                f"candidate_duplicate_tool_calls={candidate.duplicate_tool_calls} "
                f"duplicate_tool_calls_delta={comparison.duplicate_tool_calls_delta}"
            )
            print(
                f"baseline_completed={baseline.completed} candidate_completed={candidate.completed} "
                f"baseline_failed={baseline.failed} candidate_failed={candidate.failed} "
                f"correctness_preserved={comparison.correctness_preserved}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
