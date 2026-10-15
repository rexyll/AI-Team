from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from runtime.llm.base import BaseLLM, LLMResponse


@dataclass(frozen=True)
class LLMCallProfile:
    """Privacy-safe metadata for one LLM invocation; prompt contents are never stored."""

    call_index: int
    method: str
    latency_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_chars: int = 0
    system_prompt_chars: int = 0
    message_count: int = 0
    tool_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMExecutionStats:
    """Mutable per-Developer LLM telemetry accumulator."""

    calls: int = 0
    latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    profiles: list[LLMCallProfile] | None = None

    def __post_init__(self) -> None:
        if self.profiles is None:
            self.profiles = []

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
            latency = perf_counter() - started
            self.stats.calls += 1
            self.stats.latency_seconds += latency
            self.stats.profiles.append(
                LLMCallProfile(
                    call_index=self.stats.calls,
                    method="generate",
                    latency_seconds=latency,
                    prompt_chars=len(prompt or ""),
                    system_prompt_chars=len(system_prompt or ""),
                )
            )

    def generate_with_tools(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> LLMResponse:
        started = perf_counter()
        try:
            response = self.delegate.generate_with_tools(
                messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        finally:
            latency = perf_counter() - started
            self.stats.calls += 1
            self.stats.latency_seconds += latency

        usage = response.usage or {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        self.stats.input_tokens += input_tokens
        self.stats.output_tokens += output_tokens
        message_chars = sum(len(str(message.get("content") or "")) for message in messages)
        self.stats.profiles.append(
            LLMCallProfile(
                call_index=self.stats.calls,
                method="generate_with_tools",
                latency_seconds=latency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                prompt_chars=message_chars,
                message_count=len(messages),
                tool_count=len(tools or []),
            )
        )
        return response
