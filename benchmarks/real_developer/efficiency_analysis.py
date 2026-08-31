from __future__ import annotations

from dataclasses import dataclass

from .metrics import RealDeveloperBenchmarkResult


@dataclass(frozen=True)
class EfficiencyFinding:
    """Evidence-backed optimization investigation candidate."""

    kind: str
    observed: float
    message: str


def baseline_snapshot(result: RealDeveloperBenchmarkResult) -> dict[str, object]:
    """Return a stable benchmark snapshot suitable for baseline comparison."""
    if not isinstance(result, RealDeveloperBenchmarkResult):
        raise TypeError("result must be a RealDeveloperBenchmarkResult")
    category_counts = result.tool_call_category_counts
    exact_duplicate_tool_calls = category_counts.get("exact_duplicate", 0)
    return {
        "scenario": result.scenario,
        "developer_count": result.developer_count,
        "task_count": result.task_count,
        "completed": result.completed,
        "failed": result.failed,
        "blocked": result.blocked,
        "duration_seconds": result.duration_seconds,
        "llm_calls": result.llm_calls,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "tool_calls": result.tool_calls,
        "unique_tool_calls": result.unique_tool_calls,
        "duplicate_tool_calls": result.duplicate_tool_calls,
        "exact_duplicate_tool_calls": exact_duplicate_tool_calls,
        "retry_tool_calls": result.retry_tool_calls,
        "tool_result_chars": result.tool_result_chars,
        "cache_hits": result.cache_hits,
        "cache_misses": result.cache_misses,
        "cache_invalidations": result.cache_invalidations,
        "duplicate_tool_call_ratio": result.duplicate_tool_call_ratio,
        "retry_tool_call_ratio": result.retry_tool_call_ratio,
        "llm_time_ratio": result.llm_time_ratio,
        "avg_llm_calls_per_task": result.avg_llm_calls_per_task,
        "avg_tool_calls_per_task": result.avg_tool_calls_per_task,
        "tool_call_category_counts": category_counts,
    }


def identify_efficiency_candidates(result: RealDeveloperBenchmarkResult) -> tuple[EfficiencyFinding, ...]:
    """Identify measurable hotspots without claiming causality.

    Only ``exact_duplicate`` calls are treated as direct duplicate-execution
    candidates. Failure-recovery retries remain separately classified because
    repeating a failed operation can be necessary for correctness.
    """
    if not isinstance(result, RealDeveloperBenchmarkResult):
        raise TypeError("result must be a RealDeveloperBenchmarkResult")

    findings: list[EfficiencyFinding] = []
    category_counts = result.tool_call_category_counts
    exact_duplicates = category_counts.get("exact_duplicate", 0)
    if exact_duplicates:
        ratio = exact_duplicates / result.tool_calls if result.tool_calls else 0.0
        findings.append(
            EfficiencyFinding(
                kind="duplicate_tool_execution",
                observed=ratio,
                message=(
                    f"{exact_duplicates} of {result.tool_calls} tool calls were exact duplicates; "
                    "inspect whether cacheable/read-only evidence could be reused earlier. "
                    "Failure-recovery retries are excluded from this finding."
                ),
            )
        )
    if result.llm_calls > result.task_count:
        findings.append(
            EfficiencyFinding(
                kind="multi_turn_llm_execution",
                observed=result.avg_llm_calls_per_task,
                message=(
                    f"Average LLM turns per task were {result.avg_llm_calls_per_task:.2f}; "
                    "review decision turns and verification turns for avoidable repetition."
                ),
            )
        )
    if result.llm_time_ratio >= 0.90:
        findings.append(
            EfficiencyFinding(
                kind="llm_dominant_wall_time",
                observed=result.llm_time_ratio,
                message=(
                    f"LLM latency accounted for {result.llm_time_ratio:.1%} of measured "
                    "wall time; prioritize prompt/tool-result size and unnecessary turns."
                ),
            )
        )
    return tuple(findings)
