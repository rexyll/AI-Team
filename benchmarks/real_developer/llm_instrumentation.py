from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from runtime.llm.base import BaseLLM, LLMResponse


@dataclass
class LLMExecutionStats:
    """Mutable per-Developer LLM telemetry accumulator."""

    calls: int = 0
    latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class InstrumentedLLM(BaseLLM):
    """Transparent LLM decorator that records benchmark-safe telemetry."""

    def __init__(self, delegate: BaseLLM) -> None:
        if not isinstance(delegate, BaseLLM):
            raise TypeError("delegate must implement BaseLLM")
        self.delegate = delegate
        self.stats = LLMExecutionStats()

    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        started = perf_counter()
        try:
            return self.delegate.generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        finally:
            self.stats.calls += 1
            self.stats.latency_seconds += perf_counter() - started

    def generate_with_tools(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> LLMResponse:
        started = perf_counter()
        try:
            response = self.delegate.generate_with_tools(
                messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        finally:
            self.stats.calls += 1
            self.stats.latency_seconds += perf_counter() - started

        usage = response.usage or {}
        self.stats.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.stats.output_tokens += int(usage.get("completion_tokens", 0) or 0)
        return response
