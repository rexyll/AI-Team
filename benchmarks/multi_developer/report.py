from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .runner import BenchmarkResult, BenchmarkResultWithBaseline


@dataclass(frozen=True)
class BenchmarkReport:
    """Immutable report over one or more multi-Developer benchmark runs."""

    results: tuple[BenchmarkResult, ...]

    @classmethod
    def from_results(cls, results: Iterable[BenchmarkResult]) -> "BenchmarkReport":
        materialized = tuple(results)
        if any(not isinstance(result, BenchmarkResult) for result in materialized):
            raise TypeError("results must contain BenchmarkResult values")
        return cls(materialized)

    def for_scenario(self, scenario: str) -> "BenchmarkReport":
        if not isinstance(scenario, str) or not scenario.strip():
            raise ValueError("scenario must be a non-empty string")
        return BenchmarkReport(tuple(result for result in self.results if result.scenario == scenario))

    def with_baseline(self, developer_count: int = 1) -> tuple[BenchmarkResultWithBaseline, ...]:
        if not isinstance(developer_count, int) or isinstance(developer_count, bool):
            raise TypeError("developer_count must be an integer")
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")

        by_scenario: dict[str, BenchmarkResult] = {}
        for result in self.results:
            if result.developer_count == developer_count:
                by_scenario.setdefault(result.scenario, result)

        measured: list[BenchmarkResultWithBaseline] = []
        for result in self.results:
            if result.developer_count == developer_count:
                continue
            baseline = by_scenario.get(result.scenario)
            if baseline is not None:
                measured.append(result.with_baseline(baseline))
        return tuple(measured)

    def to_dict(self) -> dict[str, object]:
        return {"results": [result.to_dict() for result in self.results]}

    def render_table(self) -> str:
        """Render a stable plain-text table suitable for CI logs and reports."""
        headers = ("scenario", "developers", "tasks", "completed", "failed", "blocked", "duration_s")
        rows = [
            (
                result.scenario,
                str(result.developer_count),
                str(result.task_count),
                str(result.completed),
                str(result.failed),
                str(result.blocked),
                f"{result.duration_seconds:.6f}",
            )
            for result in self.results
        ]
        widths = [len(header) for header in headers]
        for row in rows:
            for index, value in enumerate(row):
                widths[index] = max(widths[index], len(value))

        def format_row(row: tuple[str, ...]) -> str:
            return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))

        separator = "-+-".join("-" * width for width in widths)
        output = [format_row(headers), separator]
        output.extend(format_row(row) for row in rows)
        return "\n".join(output)
