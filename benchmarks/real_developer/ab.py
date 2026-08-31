from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from unittest.mock import patch

from runtime.task import Task
from runtime.task_manager import TaskManager

from .fixture import isolated_benchmark_workspace
from .metrics import RealDeveloperBenchmarkResult
from .runner import DeveloperExecutor, RealDeveloperBenchmark


@dataclass(frozen=True)
class BenchmarkABComparison:
    """Paired baseline/candidate result for one controlled scenario."""

    baseline: RealDeveloperBenchmarkResult
    candidate: RealDeveloperBenchmarkResult

    @property
    def input_token_delta(self) -> int:
        return self.candidate.input_tokens - self.baseline.input_tokens

    @property
    def input_token_change_ratio(self) -> float:
        if self.baseline.input_tokens == 0:
            return 0.0 if self.candidate.input_tokens == 0 else float("inf")
        return self.input_token_delta / self.baseline.input_tokens

    @property
    def llm_calls_delta(self) -> int:
        return self.candidate.llm_calls - self.baseline.llm_calls

    @property
    def llm_call_change_ratio(self) -> float:
        if self.baseline.llm_calls == 0:
            return 0.0 if self.candidate.llm_calls == 0 else float("inf")
        return self.llm_calls_delta / self.baseline.llm_calls

    @property
    def duration_delta(self) -> float:
        return self.candidate.duration_seconds - self.baseline.duration_seconds

    @property
    def duration_change_ratio(self) -> float:
        if self.baseline.duration_seconds == 0:
            return 0.0 if self.candidate.duration_seconds == 0 else float("inf")
        return self.duration_delta / self.baseline.duration_seconds

    @property
    def max_context_growth_delta(self) -> float:
        return self.candidate.max_context_growth_ratio - self.baseline.max_context_growth_ratio

    @property
    def tool_result_chars_delta(self) -> int:
        return self.candidate.tool_result_chars - self.baseline.tool_result_chars

    @property
    def duplicate_tool_calls_delta(self) -> int:
        return self.candidate.duplicate_tool_calls - self.baseline.duplicate_tool_calls

    @property
    def exact_duplicate_tool_calls_delta(self) -> int:
        return (
            self.candidate.tool_call_category_counts.get("exact_duplicate", 0)
            - self.baseline.tool_call_category_counts.get("exact_duplicate", 0)
        )

    @staticmethod
    def _cache_probe_excess(result: RealDeveloperBenchmarkResult) -> int:
        if not any(item.tool_loop_telemetry for item in result.task_metrics):
            return 0
        exact = result.tool_call_category_counts.get("exact_duplicate", 0)
        return max(0, result.cache_hits - exact)

    @property
    def cache_probe_excess_delta(self) -> int:
        return self._cache_probe_excess(self.candidate) - self._cache_probe_excess(self.baseline)

    @property
    def decision_trace_delta(self) -> int:
        return self.candidate.decision_trace_count - self.baseline.decision_trace_count

    @property
    def correctness_preserved(self) -> bool:
        return (
            self.candidate.completed >= self.baseline.completed
            and self.candidate.failed <= self.baseline.failed
            and self.candidate.blocked <= self.baseline.blocked
        )

    @property
    def sample_valid(self) -> bool:
        """Whether both sides completed the workload without failure/blocking."""
        return all(
            result.failed == 0
            and result.blocked == 0
            and result.completed == result.task_count
            for result in (self.baseline, self.candidate)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "delta": {
                "input_tokens": self.input_token_delta,
                "input_token_change_ratio": self.input_token_change_ratio,
                "llm_calls": self.llm_calls_delta,
                "llm_call_change_ratio": self.llm_call_change_ratio,
                "duration_seconds": self.duration_delta,
                "duration_change_ratio": self.duration_change_ratio,
                "max_context_growth_ratio": self.max_context_growth_delta,
                "tool_result_chars": self.tool_result_chars_delta,
                "duplicate_tool_calls": self.duplicate_tool_calls_delta,
                "exact_duplicate_tool_calls": self.exact_duplicate_tool_calls_delta,
                "cache_probe_excess": self.cache_probe_excess_delta,
                "decision_trace_count": self.decision_trace_delta,
            },
            "decision_reason_counts": {
                "baseline": self.baseline.decision_trace_reason_counts,
                "candidate": self.candidate.decision_trace_reason_counts,
            },
            "correctness_preserved": self.correctness_preserved,
            "sample_valid": self.sample_valid,
        }


class RealDeveloperABBenchmark:
    """Run a fair baseline/candidate comparison on isolated workspaces.

    The baseline disables only the read-only result cache lookup. All other
    DeveloperAgent behavior, including context compaction and instrumentation,
    remains unchanged. Each side gets a fresh deterministic fixture workspace,
    preventing unrelated files in the user's projects directory from changing
    the LLM trajectory or causing missing-file failures.
    """

    def __init__(
        self,
        *,
        scenario_factory: Callable[[], list[Task]],
        executor_factory: Callable[[TaskManager, int], DeveloperExecutor],
        scenario_name: str,
    ) -> None:
        if not callable(scenario_factory):
            raise TypeError("scenario_factory must be callable")
        if not callable(executor_factory):
            raise TypeError("executor_factory must be callable")
        if not isinstance(scenario_name, str) or not scenario_name.strip():
            raise ValueError("scenario_name must be a non-empty string")
        self.scenario_factory = scenario_factory
        self.executor_factory = executor_factory
        self.scenario_name = scenario_name

    def run(self, developer_count: int) -> BenchmarkABComparison:
        baseline = self._run_once(developer_count, disable_cache=True)
        candidate = self._run_once(developer_count, disable_cache=False)
        return BenchmarkABComparison(baseline=baseline, candidate=candidate)

    def _run_once(self, developer_count: int, *, disable_cache: bool) -> RealDeveloperBenchmarkResult:
        benchmark = RealDeveloperBenchmark(
            scenario_factory=self.scenario_factory,
            executor_factory=self.executor_factory,
            scenario_name=self.scenario_name + ("-baseline" if disable_cache else "-candidate"),
        )

        with isolated_benchmark_workspace():
            if not disable_cache:
                return benchmark.run(developer_count)

            from agents import developer as developer_module

            class NoReadOnlyCache(developer_module.ToolResultCache):
                def lookup(self, tool_name, arguments):
                    if tool_name in getattr(developer_module, "CACHEABLE_TOOLS", ()):
                        return None
                    return super().lookup(tool_name, arguments)

            with patch.object(developer_module, "ToolResultCache", NoReadOnlyCache):
                return benchmark.run(developer_count)
