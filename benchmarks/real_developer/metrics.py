from __future__ import annotations

from dataclasses import dataclass

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
    failed: bool = False
    llm_profiles: tuple[LLMCallProfile, ...] = ()
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
        if self.llm_calls <= 0:
            return 0.0
        return self.llm_latency_seconds / self.llm_calls

    @property
    def llm_time_ratio(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return min(1.0, self.llm_latency_seconds / self.duration_seconds)

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

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not self.developer_id:
            raise ValueError("developer_id must be non-empty")
        if self.duration_seconds < 0 or self.llm_latency_seconds < 0:
            raise ValueError("durations must be non-negative")
        for name, value in (
            ("llm_calls", self.llm_calls),
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("tool_calls", self.tool_calls),
            ("test_commands", self.test_commands),
            ("compaction_count", self.compaction_count),
            ("max_prompt_chars_before_compaction", self.max_prompt_chars_before_compaction),
            ("max_prompt_chars_after_compaction", self.max_prompt_chars_after_compaction),
            ("max_context_messages_before_compaction", self.max_context_messages_before_compaction),
            ("max_context_messages_after_compaction", self.max_context_messages_after_compaction),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


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
    def llm_calls(self) -> int:
        return sum(item.llm_calls for item in self.task_metrics)

    @property
    def input_tokens(self) -> int:
        return sum(item.input_tokens for item in self.task_metrics)

    @property
    def output_tokens(self) -> int:
        return sum(item.output_tokens for item in self.task_metrics)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def llm_latency_seconds(self) -> float:
        return sum(item.llm_latency_seconds for item in self.task_metrics)

    @property
    def tool_calls(self) -> int:
        return sum(item.tool_calls for item in self.task_metrics)

    @property
    def test_commands(self) -> int:
        return sum(item.test_commands for item in self.task_metrics)

    @property
    def avg_llm_latency_seconds(self) -> float:
        if self.llm_calls <= 0:
            return 0.0
        return self.llm_latency_seconds / self.llm_calls

    @property
    def developer_utilization(self) -> float:
        if self.developer_count <= 0 or self.duration_seconds <= 0:
            return 0.0
        busy_time = sum(item.duration_seconds for item in self.task_metrics)
        return min(1.0, busy_time / (self.developer_count * self.duration_seconds))

    @property
    def llm_time_ratio(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return min(1.0, self.llm_latency_seconds / self.duration_seconds)

    @property
    def avg_llm_calls_per_task(self) -> float:
        return self.llm_calls / self.task_count if self.task_count else 0.0

    @property
    def avg_input_tokens_per_task(self) -> float:
        return self.input_tokens / self.task_count if self.task_count else 0.0

    @property
    def avg_tool_calls_per_task(self) -> float:
        return self.tool_calls / self.task_count if self.task_count else 0.0

    @property
    def max_llm_calls_per_task(self) -> int:
        return max((item.llm_calls for item in self.task_metrics), default=0)

    @property
    def max_prompt_chars_per_task(self) -> int:
        return max((item.max_prompt_chars for item in self.task_metrics), default=0)

    @property
    def max_input_tokens_per_call(self) -> int:
        return max((item.max_input_tokens for item in self.task_metrics), default=0)

    @property
    def max_context_growth_ratio(self) -> float:
        return max((item.context_growth_ratio for item in self.task_metrics), default=0.0)

    @property
    def compaction_count(self) -> int:
        return sum(item.compaction_count for item in self.task_metrics)

    @property
    def max_prompt_chars_before_compaction(self) -> int:
        return max((item.max_prompt_chars_before_compaction for item in self.task_metrics), default=0)

    @property
    def max_prompt_chars_after_compaction(self) -> int:
        return max((item.max_prompt_chars_after_compaction for item in self.task_metrics), default=0)

    @property
    def max_context_messages_before_compaction(self) -> int:
        return max((item.max_context_messages_before_compaction for item in self.task_metrics), default=0)

    @property
    def max_context_messages_after_compaction(self) -> int:
        return max((item.max_context_messages_after_compaction for item in self.task_metrics), default=0)

    @property
    def cost_per_completed_task_tokens(self) -> float:
        if self.completed <= 0:
            return float("inf")
        return self.total_tokens / self.completed

    @classmethod
    def from_task_metrics(cls, *, scenario: str, developer_count: int, task_count: int, completed: int, failed: int, blocked: int, duration_seconds: float, task_metrics: tuple[RealDeveloperTaskMetrics, ...]) -> "RealDeveloperBenchmarkResult":
        if not scenario.strip():
            raise ValueError("scenario must be non-empty")
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")
        if task_count < 0 or completed < 0 or failed < 0 or blocked < 0:
            raise ValueError("task counts must be non-negative")
        if duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        return cls(scenario=scenario, developer_count=developer_count, task_count=task_count, completed=completed, failed=failed, blocked=blocked, duration_seconds=duration_seconds, task_metrics=task_metrics)

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "developer_count": self.developer_count,
            "task_count": self.task_count,
            "completed": self.completed,
            "failed": self.failed,
            "blocked": self.blocked,
            "duration_seconds": self.duration_seconds,
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "llm_latency_seconds": self.llm_latency_seconds,
            "avg_llm_latency_seconds": self.avg_llm_latency_seconds,
            "llm_time_ratio": self.llm_time_ratio,
            "tool_calls": self.tool_calls,
            "test_commands": self.test_commands,
            "developer_utilization": self.developer_utilization,
            "avg_llm_calls_per_task": self.avg_llm_calls_per_task,
            "avg_input_tokens_per_task": self.avg_input_tokens_per_task,
            "avg_tool_calls_per_task": self.avg_tool_calls_per_task,
            "max_llm_calls_per_task": self.max_llm_calls_per_task,
            "max_prompt_chars_per_task": self.max_prompt_chars_per_task,
            "max_input_tokens_per_call": self.max_input_tokens_per_call,
            "max_context_growth_ratio": self.max_context_growth_ratio,
            "compaction_count": self.compaction_count,
            "max_prompt_chars_before_compaction": self.max_prompt_chars_before_compaction,
            "max_prompt_chars_after_compaction": self.max_prompt_chars_after_compaction,
            "max_context_messages_before_compaction": self.max_context_messages_before_compaction,
            "max_context_messages_after_compaction": self.max_context_messages_after_compaction,
            "cost_per_completed_task_tokens": self.cost_per_completed_task_tokens,
        }
