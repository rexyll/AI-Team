from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, median, stdev
from typing import Iterable


@dataclass(frozen=True)
class BenchmarkStatistics:
    """Descriptive statistics for repeated benchmark durations."""

    scenario: str
    developer_count: int
    runs: int
    mean_seconds: float
    median_seconds: float
    min_seconds: float
    max_seconds: float
    stddev_seconds: float
    coefficient_of_variation: float

    @classmethod
    def from_durations(
        cls,
        scenario: str,
        developer_count: int,
        durations: Iterable[float],
    ) -> "BenchmarkStatistics":
        values = tuple(float(value) for value in durations)
        if not values:
            raise ValueError("durations must contain at least one value")
        if any(value < 0 for value in values):
            raise ValueError("durations must be non-negative")
        if not isinstance(developer_count, int) or isinstance(developer_count, bool):
            raise TypeError("developer_count must be an integer")
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")
        if not isinstance(scenario, str) or not scenario.strip():
            raise ValueError("scenario must be a non-empty string")

        average = mean(values)
        deviation = stdev(values) if len(values) > 1 else 0.0
        return cls(
            scenario=scenario,
            developer_count=developer_count,
            runs=len(values),
            mean_seconds=average,
            median_seconds=median(values),
            min_seconds=min(values),
            max_seconds=max(values),
            stddev_seconds=deviation,
            coefficient_of_variation=(deviation / average if average else 0.0),
        )

    def speedup_against(self, baseline: "BenchmarkStatistics") -> float:
        if baseline.scenario != self.scenario:
            raise ValueError("baseline scenario must match")
        if baseline.mean_seconds <= 0 or self.mean_seconds <= 0:
            return 0.0
        return baseline.mean_seconds / self.mean_seconds

    def efficiency_against(self, baseline: "BenchmarkStatistics") -> float:
        return self.speedup_against(baseline) / self.developer_count

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "developer_count": self.developer_count,
            "runs": self.runs,
            "mean_seconds": self.mean_seconds,
            "median_seconds": self.median_seconds,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "stddev_seconds": self.stddev_seconds,
            "coefficient_of_variation": self.coefficient_of_variation,
        }
