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
    parser.add_argument(
        "--require-valid-sample",
        action="store_true",
        help="Exit non-zero when any baseline/candidate sample is incomplete or failed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if any(count <= 0 for count in args.developers):
        raise SystemExit("--developers values must be greater than 0")

    executor_factory = build_live_executor_factory(provider_profile=args.provider, model=args.model)
    invalid_samples: list[int] = []
    for developer_count in args.developers:
        comparison = RealDeveloperABBenchmark(
            scenario_factory=SCENARIOS[args.scenario],
            executor_factory=executor_factory,
            scenario_name=args.scenario,
        ).run(developer_count)
        if not comparison.sample_valid:
            invalid_samples.append(developer_count)
        payload = comparison.to_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            baseline = comparison.baseline
            candidate = comparison.candidate
            print(
                f"scenario={args.scenario} developers={developer_count} "
                f"sample_valid={comparison.sample_valid} "
                f"correctness_preserved={comparison.correctness_preserved}"
            )
            print(
                f"baseline_llm_calls={baseline.llm_calls} candidate_llm_calls={candidate.llm_calls} "
                f"llm_calls_delta={comparison.llm_calls_delta} "
                f"llm_call_change_ratio={comparison.llm_call_change_ratio:.4f}"
            )
            print(
                f"baseline_duration_seconds={baseline.duration_seconds:.3f} "
                f"candidate_duration_seconds={candidate.duration_seconds:.3f} "
                f"duration_delta={comparison.duration_delta:.3f} "
                f"duration_change_ratio={comparison.duration_change_ratio:.4f}"
            )
            print(
                f"baseline_input_tokens={baseline.input_tokens} candidate_input_tokens={candidate.input_tokens} "
                f"input_token_delta={comparison.input_token_delta} "
                f"input_token_change_ratio={comparison.input_token_change_ratio:.4f}"
            )
            print(
                f"baseline_exact_duplicate_tool_calls={baseline.tool_call_category_counts.get('exact_duplicate', 0)} "
                f"candidate_exact_duplicate_tool_calls={candidate.tool_call_category_counts.get('exact_duplicate', 0)} "
                f"exact_duplicate_tool_calls_delta={comparison.exact_duplicate_tool_calls_delta}"
            )
            print(
                f"baseline_cache_probe_excess={comparison._cache_probe_excess(baseline)} "
                f"candidate_cache_probe_excess={comparison._cache_probe_excess(candidate)} "
                f"cache_probe_excess_delta={comparison.cache_probe_excess_delta}"
            )
            print(
                f"baseline_decision_traces={baseline.decision_trace_count} "
                f"candidate_decision_traces={candidate.decision_trace_count} "
                f"decision_trace_delta={comparison.decision_trace_delta}"
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
    if args.require_valid_sample and invalid_samples:
        counts = ", ".join(str(count) for count in invalid_samples)
        print(f"invalid benchmark samples for developer counts: {counts}", file=__import__("sys").stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
