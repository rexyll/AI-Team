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
            result = RealDeveloperBenchmark(scenario_factory=SCENARIOS[args.scenario], executor_factory=executor_factory, scenario_name=args.scenario).run(developer_count)
            results.append(result)
            print(
                f"scenario={result.scenario} developers={result.developer_count} tasks={result.task_count} completed={result.completed} failed={result.failed} blocked={result.blocked} "
                f"duration_s={result.duration_seconds:.3f} llm_calls={result.llm_calls} input_tokens={result.input_tokens} output_tokens={result.output_tokens} tool_calls={result.tool_calls} test_commands={result.test_commands} "
                f"unique_tool_calls={result.unique_tool_calls} duplicate_tool_calls={result.duplicate_tool_calls} retry_tool_calls={result.retry_tool_calls} tool_result_chars={result.tool_result_chars} largest_tool_result_chars={result.largest_tool_result_chars} "
                f"avg_llm_latency_s={result.avg_llm_latency_seconds:.3f} llm_time_ratio={result.llm_time_ratio:.3f} utilization={result.developer_utilization:.3f} max_prompt_chars={result.max_prompt_chars_per_task} "
                f"max_input_tokens_per_call={result.max_input_tokens_per_call} max_context_growth_ratio={result.max_context_growth_ratio:.3f}"
            )
            for metric in result.task_metrics:
                print(
                    f"  task={metric.task_id} developer={metric.developer_id} duration_s={metric.duration_seconds:.3f} llm_calls={metric.llm_calls} input_tokens={metric.input_tokens} output_tokens={metric.output_tokens} "
                    f"tool_calls={metric.tool_calls} unique_tool_calls={metric.unique_tool_calls} duplicate_tool_calls={metric.duplicate_tool_calls} retry_tool_calls={metric.retry_tool_calls} "
                    f"tool_result_chars={metric.tool_result_chars} largest_tool_result_chars={metric.largest_tool_result_chars} test_commands={metric.test_commands} failed={metric.failed} "
                    f"max_prompt_chars={metric.max_prompt_chars} max_input_tokens={metric.max_input_tokens} context_growth_ratio={metric.context_growth_ratio:.3f}"
                )
                if metric.llm_profiles:
                    print("    llm_profile:")
                    for profile in metric.llm_profiles:
                        print(
                            f"      call={profile.call_index} method={profile.method} latency_s={profile.latency_seconds:.3f} input_tokens={profile.input_tokens} output_tokens={profile.output_tokens} "
                            f"prompt_chars={profile.prompt_chars} system_prompt_chars={profile.system_prompt_chars} messages={profile.message_count} tools={profile.tool_count}"
                        )
        if len(results) > 1:
            mean_duration = sum(item.duration_seconds for item in results) / len(results)
            mean_calls = sum(item.llm_calls for item in results) / len(results)
            mean_tokens = sum(item.total_tokens for item in results) / len(results)
            print(f"aggregate developers={developer_count} runs={len(results)} mean_duration_s={mean_duration:.3f} mean_llm_calls={mean_calls:.1f} mean_total_tokens={mean_tokens:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
