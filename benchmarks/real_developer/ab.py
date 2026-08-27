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
    def max_context_growth_delta(self) -> float:
        return self.candidate.max_context_growth_ratio - self.baseline.max_context_growth_ratio

    @property
    def tool_result_chars_delta(self) -> int:
        return self.candidate.tool_result_chars - self.baseline.tool_result_chars

    @property
    def duplicate_tool_calls_delta(self) -> int:
        return self.candidate.duplicate_tool_calls - self.baseline.duplicate_tool_calls

    @property
    def correctness_preserved(self) -> bool:
        return (
            self.candidate.completed >= self.baseline.completed
            and self.candidate.failed <= self.baseline.failed
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
                "max_context_growth_ratio": self.max_context_growth_delta,
                "tool_result_chars": self.tool_result_chars_delta,
                "duplicate_tool_calls": self.duplicate_tool_calls_delta,
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

            # DeveloperAgent imports ToolResultCache into its module namespace,
            # so replacing that binding creates a legacy baseline without
            # modifying production code or the candidate implementation.
            from agents import developer as developer_module

            original = developer_module.ToolResultCache

            class NoReadOnlyCache(original):
                def lookup(self, tool_name, arguments):
                    if tool_name in getattr(developer_module, "CACHEABLE_TOOLS", ()):
                        return None
                    return super().lookup(tool_name, arguments)

            with patch.object(developer_module, "ToolResultCache", NoReadOnlyCache):
                return benchmark.run(developer_count)
