from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .llm_instrumentation import LLMCallProfile


@dataclass(frozen=True)
class RealDeveloperTaskMetrics:
    """Instrumentation for one Developer task execution."""

    task_id: str
    developer_id: str
    duration_seconds: float
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_latency_seconds: float = 0.0
    tool_calls: int = 0
    test_commands: int = 0
    unique_tool_calls: int = 0
    duplicate_tool_calls: int = 0
    retry_tool_calls: int = 0
    tool_result_chars: int = 0
    largest_tool_result_chars: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_invalidations: int = 0
    failed: bool = False
    llm_profiles: tuple[LLMCallProfile, ...] = ()
    tool_loop_telemetry: tuple[dict[str, Any], ...] = ()
    compaction_count: int = 0
    max_prompt_chars_before_compaction: int = 0
    max_prompt_chars_after_compaction: int = 0
    max_context_messages_before_compaction: int = 0
    max_context_messages_after_compaction: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def avg_llm_latency_seconds(self) -> float:
        return self.llm_latency_seconds / self.llm_calls if self.llm_calls else 0.0

    @property
    def llm_time_ratio(self) -> float:
        return min(1.0, self.llm_latency_seconds / self.duration_seconds) if self.duration_seconds > 0 else 0.0

    @property
    def max_prompt_chars(self) -> int:
        return max((item.prompt_chars for item in self.llm_profiles), default=0)

    @property
    def max_input_tokens(self) -> int:
        return max((item.input_tokens for item in self.llm_profiles), default=0)

    @property
    def context_growth_ratio(self) -> float:
        prompts = [item.prompt_chars for item in self.llm_profiles if item.prompt_chars > 0]
        if len(prompts) < 2 or prompts[0] <= 0:
            return 1.0 if prompts else 0.0
        return prompts[-1] / prompts[0]

    @property
    def duplicate_tool_call_ratio(self) -> float:
        return self.duplicate_tool_calls / self.tool_calls if self.tool_calls else 0.0

    @property
    def retry_tool_call_ratio(self) -> float:
        return self.retry_tool_calls / self.tool_calls if self.tool_calls else 0.0

    @property
    def unique_tool_call_ratio(self) -> float:
        return self.unique_tool_calls / self.tool_calls if self.tool_calls else 0.0

    @property
    def avg_tool_result_chars(self) -> float:
        return self.tool_result_chars / self.tool_calls if self.tool_calls else 0.0

    @property
    def tool_call_category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.tool_loop_telemetry:
            category = str(item.get("category") or "other")
            counts[category] = counts.get(category, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def cache_hit_ratio(self) -> float:
        lookups = self.cache_hits + self.cache_misses
        return self.cache_hits / lookups if lookups else 0.0

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not self.developer_id:
            raise ValueError("developer_id must be non-empty")
        if self.duration_seconds < 0 or self.llm_latency_seconds < 0:
            raise ValueError("durations must be non-negative")
        for name, value in (
            ("llm_calls", self.llm_calls), ("input_tokens", self.input_tokens), ("output_tokens", self.output_tokens),
            ("tool_calls", self.tool_calls), ("test_commands", self.test_commands), ("unique_tool_calls", self.unique_tool_calls),
            ("duplicate_tool_calls", self.duplicate_tool_calls), ("retry_tool_calls", self.retry_tool_calls),
            ("tool_result_chars", self.tool_result_chars), ("largest_tool_result_chars", self.largest_tool_result_chars),
            ("cache_hits", self.cache_hits), ("cache_misses", self.cache_misses), ("cache_invalidations", self.cache_invalidations),
            ("compaction_count", self.compaction_count), ("max_prompt_chars_before_compaction", self.max_prompt_chars_before_compaction),
            ("max_prompt_chars_after_compaction", self.max_prompt_chars_after_compaction),
            ("max_context_messages_before_compaction", self.max_context_messages_before_compaction),
            ("max_context_messages_after_compaction", self.max_context_messages_after_compaction),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.duplicate_tool_calls > self.tool_calls or self.unique_tool_calls > self.tool_calls:
            raise ValueError("tool-loop counts cannot exceed tool_calls")
        if self.retry_tool_calls > self.duplicate_tool_calls:
            raise ValueError("retry_tool_calls cannot exceed duplicate_tool_calls")


@dataclass(frozen=True)
class RealDeveloperBenchmarkResult:
    """Aggregated metrics for one controlled real-Developer benchmark run."""

    scenario: str
    developer_count: int
    task_count: int
    completed: int
    failed: int
    blocked: int
    duration_seconds: float
    task_metrics: tuple[RealDeveloperTaskMetrics, ...] = ()

    @property
    def llm_calls(self) -> int: return sum(item.llm_calls for item in self.task_metrics)
    @property
    def input_tokens(self) -> int: return sum(item.input_tokens for item in self.task_metrics)
    @property
    def output_tokens(self) -> int: return sum(item.output_tokens for item in self.task_metrics)
    @property
    def total_tokens(self) -> int: return self.input_tokens + self.output_tokens
    @property
    def llm_latency_seconds(self) -> float: return sum(item.llm_latency_seconds for item in self.task_metrics)
    @property
    def tool_calls(self) -> int: return sum(item.tool_calls for item in self.task_metrics)
    @property
    def test_commands(self) -> int: return sum(item.test_commands for item in self.task_metrics)
    @property
    def unique_tool_calls(self) -> int: return sum(item.unique_tool_calls for item in self.task_metrics)
    @property
    def duplicate_tool_calls(self) -> int: return sum(item.duplicate_tool_calls for item in self.task_metrics)
    @property
    def retry_tool_calls(self) -> int: return sum(item.retry_tool_calls for item in self.task_metrics)
    @property
    def tool_result_chars(self) -> int: return sum(item.tool_result_chars for item in self.task_metrics)
    @property
    def largest_tool_result_chars(self) -> int: return max((item.largest_tool_result_chars for item in self.task_metrics), default=0)
    @property
    def cache_hits(self) -> int: return sum(item.cache_hits for item in self.task_metrics)
    @property
    def cache_misses(self) -> int: return sum(item.cache_misses for item in self.task_metrics)
    @property
    def cache_invalidations(self) -> int: return sum(item.cache_invalidations for item in self.task_metrics)
    @property
    def cache_hit_ratio(self) -> float:
        lookups = self.cache_hits + self.cache_misses
        return self.cache_hits / lookups if lookups else 0.0
    @property
    def duplicate_tool_call_ratio(self) -> float: return self.duplicate_tool_calls / self.tool_calls if self.tool_calls else 0.0
    @property
    def retry_tool_call_ratio(self) -> float: return self.retry_tool_calls / self.tool_calls if self.tool_calls else 0.0
    @property
    def unique_tool_call_ratio(self) -> float: return self.unique_tool_calls / self.tool_calls if self.tool_calls else 0.0
    @property
    def avg_tool_result_chars(self) -> float: return self.tool_result_chars / self.tool_calls if self.tool_calls else 0.0
    @property
    def tool_call_category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.task_metrics:
            for category, count in item.tool_call_category_counts.items():
                counts[category] = counts.get(category, 0) + count
        return dict(sorted(counts.items()))
    @property
    def avg_llm_latency_seconds(self) -> float: return self.llm_latency_seconds / self.llm_calls if self.llm_calls else 0.0
    @property
    def developer_utilization(self) -> float:
        if self.developer_count <= 0 or self.duration_seconds <= 0: return 0.0
        return min(1.0, sum(item.duration_seconds for item in self.task_metrics) / (self.developer_count * self.duration_seconds))
    @property
    def llm_time_ratio(self) -> float: return min(1.0, self.llm_latency_seconds / self.duration_seconds) if self.duration_seconds > 0 else 0.0
    @property
    def avg_llm_calls_per_task(self) -> float: return self.llm_calls / self.task_count if self.task_count else 0.0
    @property
    def avg_input_tokens_per_task(self) -> float: return self.input_tokens / self.task_count if self.task_count else 0.0
    @property
    def avg_tool_calls_per_task(self) -> float: return self.tool_calls / self.task_count if self.task_count else 0.0
    @property
    def max_llm_calls_per_task(self) -> int: return max((item.llm_calls for item in self.task_metrics), default=0)
    @property
    def max_prompt_chars_per_task(self) -> int: return max((item.max_prompt_chars for item in self.task_metrics), default=0)
    @property
    def max_input_tokens_per_call(self) -> int: return max((item.max_input_tokens for item in self.task_metrics), default=0)
    @property
    def max_context_growth_ratio(self) -> float: return max((item.context_growth_ratio for item in self.task_metrics), default=0.0)
    @property
    def compaction_count(self) -> int: return sum(item.compaction_count for item in self.task_metrics)
    @property
    def max_prompt_chars_before_compaction(self) -> int: return max((item.max_prompt_chars_before_compaction for item in self.task_metrics), default=0)
    @property
    def max_prompt_chars_after_compaction(self) -> int: return max((item.max_prompt_chars_after_compaction for item in self.task_metrics), default=0)
    @property
    def max_context_messages_before_compaction(self) -> int: return max((item.max_context_messages_before_compaction for item in self.task_metrics), default=0)
    @property
    def max_context_messages_after_compaction(self) -> int: return max((item.max_context_messages_after_compaction for item in self.task_metrics), default=0)
    @property
    def cost_per_completed_task_tokens(self) -> float: return self.total_tokens / self.completed if self.completed > 0 else float("inf")

    @classmethod
    def from_task_metrics(cls, *, scenario: str, developer_count: int, task_count: int, completed: int, failed: int, blocked: int, duration_seconds: float, task_metrics: tuple[RealDeveloperTaskMetrics, ...]) -> "RealDeveloperBenchmarkResult":
        if not scenario.strip(): raise ValueError("scenario must be non-empty")
        if developer_count <= 0: raise ValueError("developer_count must be greater than 0")
        if min(task_count, completed, failed, blocked) < 0: raise ValueError("task counts must be non-negative")
        if duration_seconds < 0: raise ValueError("duration_seconds must be non-negative")
        return cls(scenario=scenario, developer_count=developer_count, task_count=task_count, completed=completed, failed=failed, blocked=blocked, duration_seconds=duration_seconds, task_metrics=task_metrics)

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario, "developer_count": self.developer_count, "task_count": self.task_count,
            "completed": self.completed, "failed": self.failed, "blocked": self.blocked, "duration_seconds": self.duration_seconds,
            "llm_calls": self.llm_calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "total_tokens": self.total_tokens,
            "llm_latency_seconds": self.llm_latency_seconds, "avg_llm_latency_seconds": self.avg_llm_latency_seconds, "llm_time_ratio": self.llm_time_ratio,
            "tool_calls": self.tool_calls, "test_commands": self.test_commands, "unique_tool_calls": self.unique_tool_calls,
            "duplicate_tool_calls": self.duplicate_tool_calls, "retry_tool_calls": self.retry_tool_calls, "tool_result_chars": self.tool_result_chars,
            "largest_tool_result_chars": self.largest_tool_result_chars, "cache_hits": self.cache_hits, "cache_misses": self.cache_misses,
            "cache_invalidations": self.cache_invalidations, "cache_hit_ratio": self.cache_hit_ratio,
            "duplicate_tool_call_ratio": self.duplicate_tool_call_ratio, "retry_tool_call_ratio": self.retry_tool_call_ratio,
            "unique_tool_call_ratio": self.unique_tool_call_ratio, "avg_tool_result_chars": self.avg_tool_result_chars,
            "tool_call_category_counts": self.tool_call_category_counts,
            "developer_utilization": self.developer_utilization, "avg_llm_calls_per_task": self.avg_llm_calls_per_task,
            "avg_input_tokens_per_task": self.avg_input_tokens_per_task, "avg_tool_calls_per_task": self.avg_tool_calls_per_task,
            "max_llm_calls_per_task": self.max_llm_calls_per_task, "max_prompt_chars_per_task": self.max_prompt_chars_per_task,
            "max_input_tokens_per_call": self.max_input_tokens_per_call, "max_context_growth_ratio": self.max_context_growth_ratio,
            "compaction_count": self.compaction_count, "max_prompt_chars_before_compaction": self.max_prompt_chars_before_compaction,
            "max_prompt_chars_after_compaction": self.max_prompt_chars_after_compaction,
            "max_context_messages_before_compaction": self.max_context_messages_before_compaction,
            "max_context_messages_after_compaction": self.max_context_messages_after_compaction,
            "cost_per_completed_task_tokens": self.cost_per_completed_task_tokens,
        }
