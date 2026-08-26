from __future__ import annotations

from typing import Any

from runtime.context_compaction import ContextCompactor
from runtime.llm.base import BaseLLM, LLMResponse


class ContextCompactingLLM(BaseLLM):
    """Developer LLM decorator with one authoritative hard context budget."""

    def __init__(self, inner: BaseLLM, *, recent_messages: int = 12, max_tool_chars: int = 12_000) -> None:
        if not isinstance(inner, BaseLLM):
            raise TypeError(
                "ContextCompactingLLM inner must implement BaseLLM, "
                f"got {type(inner).__name__}"
            )
        if recent_messages < 0:
            raise ValueError("recent_messages must be >= 0")
        if max_tool_chars <= 0:
            raise ValueError("max_tool_chars must be > 0")
        self.inner = inner
        self.recent_messages = recent_messages
        self.max_tool_chars = max_tool_chars
        self.calls = 0
        self.compaction_count = 0
        self.max_prompt_chars_before = 0
        self.max_prompt_chars_after = 0
        self.max_input_messages_before = 0
        self.max_input_messages_after = 0
        self.compaction_events: list[dict[str, int | bool]] = []
        self.context_compactor = ContextCompactor()
        self._last_prompt_chars_before = 0
        self._last_prompt_chars_after = 0
        self._last_input_tokens_before = 0
        self._last_input_tokens_after = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    @property
    def last_prompt_chars_before(self) -> int:
        return self._last_prompt_chars_before

    @property
    def last_prompt_chars_after(self) -> int:
        return self._last_prompt_chars_after

    @property
    def last_input_tokens_before(self) -> int:
        return self._last_input_tokens_before

    @property
    def last_input_tokens_after(self) -> int:
        return self._last_input_tokens_after

    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        compact_prompt, compact_system, _ = self.context_compactor.compact_prompt(prompt, system_prompt=system_prompt)
        return self.inner.generate(compact_prompt, system_prompt=compact_system, temperature=temperature, max_tokens=max_tokens)

    def generate_with_tools(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> LLMResponse:
        before = [dict(message) for message in messages]
        windowed = self._apply_recent_window(before)
        active, stats = self.context_compactor.compact_messages(windowed)

        self.calls += 1
        self._last_prompt_chars_before = stats.original_chars
        self._last_prompt_chars_after = stats.compacted_chars
        self._last_input_tokens_before = stats.original_tokens
        self._last_input_tokens_after = stats.compacted_tokens
        self.max_prompt_chars_before = max(self.max_prompt_chars_before, stats.original_chars)
        self.max_prompt_chars_after = max(self.max_prompt_chars_after, stats.compacted_chars)
        self.max_input_messages_before = max(self.max_input_messages_before, len(before))
        self.max_input_messages_after = max(self.max_input_messages_after, len(active))
        compacted = active != before
        if compacted:
            self.compaction_count += 1
        self.compaction_events.append({
            "call_index": self.calls,
            "compacted": compacted,
            "prompt_chars_before": stats.original_chars,
            "prompt_chars_after": stats.compacted_chars,
            "messages_before": len(before),
            "messages_after": len(active),
            "input_tokens_before": stats.original_tokens,
            "input_tokens_after": stats.compacted_tokens,
        })
        return self.inner.generate_with_tools(active, tools=tools, tool_choice=tool_choice)

    def _apply_recent_window(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Preserve the stable prefix and recent tail used by the legacy decorator.

        The hard character/token budget remains the authoritative final guard.
        This lightweight window only removes stale turns before that guard and
        therefore does not create a second independent budget policy.
        """
        if len(messages) <= self.recent_messages + 3:
            return messages
        prefix_count = min(2, len(messages))
        prefix = messages[:prefix_count]
        tail_count = self.recent_messages + 1
        tail = messages[-tail_count:] if tail_count else []
        selected_indexes = {id(message) for message in prefix + tail}
        return [message for message in messages if id(message) in selected_indexes]
