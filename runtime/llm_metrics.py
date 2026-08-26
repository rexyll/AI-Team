from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from runtime.context_compaction import estimate_tokens


@dataclass(frozen=True)
class LLMMetricsSnapshot:
    llm_calls: int
    tool_calls: int
    total_llm_seconds: float
    max_prompt_chars: int
    max_input_tokens_per_call: int
    initial_prompt_chars: int
    context_growth_ratio: float

    @property
    def llm_time_ratio(self) -> float:
        """Fraction of observed wall-clock time spent inside LLM calls.

        The caller records the overall agent wall time through ``finish()``.
        A zero-duration execution reports 0 rather than manufacturing a
        percentage.
        """
        return self._llm_time_ratio

    _llm_time_ratio: float = 0.0


class LLMMetrics:
    """Lightweight per-agent instrumentation for prompt/runtime behavior."""

    def __init__(self) -> None:
        self._llm_calls = 0
        self._tool_calls = 0
        self._total_llm_seconds = 0.0
        self._max_prompt_chars = 0
        self._max_input_tokens = 0
        self._initial_prompt_chars = 0
        self._wall_started = perf_counter()
        self._finished = False
        self._llm_time_ratio = 0.0

    def record_llm_call(self, prompt_chars: int, input_tokens: int, elapsed_seconds: float) -> None:
        if prompt_chars < 0 or input_tokens < 0 or elapsed_seconds < 0:
            raise ValueError("LLM metrics values must be non-negative")

        self._llm_calls += 1
        self._total_llm_seconds += elapsed_seconds
        self._max_prompt_chars = max(self._max_prompt_chars, prompt_chars)
        self._max_input_tokens = max(self._max_input_tokens, input_tokens)
        if self._llm_calls == 1:
            self._initial_prompt_chars = prompt_chars

    def record_tool_calls(self, count: int) -> None:
        if count < 0:
            raise ValueError("tool call count must be non-negative")
        self._tool_calls += count

    def finish(self, wall_seconds: float | None = None) -> None:
        if wall_seconds is None:
            wall_seconds = perf_counter() - self._wall_started
        if wall_seconds < 0:
            raise ValueError("wall_seconds must be non-negative")
        self._llm_time_ratio = (
            min(1.0, self._total_llm_seconds / wall_seconds)
            if wall_seconds
            else 0.0
        )
        self._finished = True

    def snapshot(self) -> LLMMetricsSnapshot:
        growth_ratio = (
            self._max_prompt_chars / self._initial_prompt_chars
            if self._initial_prompt_chars
            else 1.0
        )
        return LLMMetricsSnapshot(
            llm_calls=self._llm_calls,
            tool_calls=self._tool_calls,
            total_llm_seconds=self._total_llm_seconds,
            max_prompt_chars=self._max_prompt_chars,
            max_input_tokens_per_call=self._max_input_tokens,
            initial_prompt_chars=self._initial_prompt_chars,
            context_growth_ratio=growth_ratio,
            _llm_time_ratio=self._llm_time_ratio,
        )

    @staticmethod
    def measure_text(text: str) -> tuple[int, int]:
        return len(text), estimate_tokens(text)
