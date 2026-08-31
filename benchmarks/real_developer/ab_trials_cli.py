from __future__ import annotations

import argparse
import json
import sys

from .ab import RealDeveloperABBenchmark
from .ab_trials import BenchmarkABTrialSummary
from .live import build_live_executor_factory
from .scenarios import independent_implementation_tasks, partial_implementation_tasks, serial_implementation_tasks

SCENARIOS = {
    "independent": independent_implementation_tasks,
    "partial": partial_implementation_tasks,
    "serial": serial_implementation_tasks,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run repeated live Developer A/B trials and summarize only valid paired samples."
    )
    parser.add_argument("--developers", type=int, nargs="+", default=[1])
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), default="serial")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-valid-trial",
        action="store_true",
        help="Exit non-zero unless every requested trial is valid.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if any(count <= 0 for count in args.developers):
        raise SystemExit("--developers values must be greater than 0")
    if args.trials <= 0:
        raise SystemExit("--trials must be greater than 0")

    executor_factory = build_live_executor_factory(provider_profile=args.provider, model=args.model)
    exit_code = 0
    for developer_count in args.developers:
        benchmark = RealDeveloperABBenchmark(
            scenario_factory=SCENARIOS[args.scenario],
            executor_factory=executor_factory,
            scenario_name=args.scenario,
        )
        comparisons = []
        invalid_trial_numbers: list[int] = []
        for trial_index in range(1, args.trials + 1):
            comparison = benchmark.run(developer_count)
            comparisons.append(comparison)
            if not comparison.sample_valid:
                invalid_trial_numbers.append(trial_index)

        summary = BenchmarkABTrialSummary.from_comparisons(comparisons)
        payload = {
            "scenario": args.scenario,
            "developers": developer_count,
            "summary": summary.to_dict(),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                f"scenario={args.scenario} developers={developer_count} trials={summary.trials} "
                f"valid_trials={summary.valid_trials} invalid_trials={summary.invalid_trials} "
                f"valid_sample_rate={summary.valid_trials / summary.trials:.4f}"
            )
            print(
                f"baseline_success_rate={summary.baseline_success_rate:.4f} "
                f"candidate_success_rate={summary.candidate_success_rate:.4f}"
            )
            print(
                f"median_duration_change_ratio={summary.median_duration_change_ratio} "
                f"median_llm_call_change_ratio={summary.median_llm_call_change_ratio} "
                f"median_input_token_change_ratio={summary.median_input_token_change_ratio}"
            )
            print(
                f"median_exact_duplicate_tool_calls_delta={summary.median_exact_duplicate_tool_calls_delta} "
                f"median_duplicate_execution_tool_calls_delta={summary.median_duplicate_execution_tool_calls_delta} "
                f"median_cache_hits_delta={summary.median_cache_hits_delta} "
                f"median_decision_trace_delta={summary.median_decision_trace_delta}"
            )
            if invalid_trial_numbers:
                print(f"invalid_trials={invalid_trial_numbers}")

        if args.require_valid_trial and invalid_trial_numbers:
            exit_code = 2

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
