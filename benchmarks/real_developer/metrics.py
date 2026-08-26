from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class RealDeveloperTaskMetrics:
    """Instrumentation for one Developer task execution."""

    task_id: str
    developer_id: str
    duration_seconds: float
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failed: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not self.developer_id:
            raise ValueError("developer_id must be non-empty")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        for name, value in (("llm_calls", self.llm_calls), ("input_tokens", self.input_tokens), ("output_tokens", self.output_tokens)):
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
    def developer_utilization(self) -> float:
        if self.developer_count <= 0 or self.duration_seconds <= 0:
            return 0.0
        busy_time = sum(item.duration_seconds for item in self.task_metrics)
        return min(1.0, busy_time / (self.developer_count * self.duration_seconds))

    @property
    def cost_per_completed_task_tokens(self) -> float:
        if self.completed <= 0:
            return float("inf")
        return self.total_tokens / self.completed

    @classmethod
    def from_task_metrics(
        cls,
        *,
        scenario: str,
        developer_count: int,
        task_count: int,
        completed: int,
        failed: int,
        blocked: int,
        duration_seconds: float,
        task_metrics: tuple[RealDeveloperTaskMetrics, ...],
    ) -> "RealDeveloperBenchmarkResult":
        if not scenario.strip():
            raise ValueError("scenario must be non-empty")
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")
        if task_count < 0 or completed < 0 or failed < 0 or blocked < 0:
            raise ValueError("task counts must be non-negative")
        if duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        return cls(
            scenario=scenario,
            developer_count=developer_count,
            task_count=task_count,
            completed=completed,
            failed=failed,
            blocked=blocked,
            duration_seconds=duration_seconds,
            task_metrics=task_metrics,
        )

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
            "developer_utilization": self.developer_utilization,
            "cost_per_completed_task_tokens": self.cost_per_completed_task_tokens,
        }
