from __future__ import annotations

from typing import Any

from runtime.context_compactor import compact_tool_context
from runtime.llm.base import BaseLLM, LLMResponse


class ContextCompactingLLM(BaseLLM):
    """LLM decorator that bounds the active tool-loop context per request."""

    def __init__(
        self,
        inner: BaseLLM,
        *,
        recent_messages: int = 12,
        max_tool_chars: int = 12_000,
    ) -> None:
        if not isinstance(inner, BaseLLM):
            raise TypeError(
                "ContextCompactingLLM inner must implement BaseLLM, "
                f"got {type(inner).__name__}"
            )
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

    def __getattr__(self, name: str) -> Any:
        """Preserve access to telemetry/config attributes on wrapped LLMs."""
        return getattr(self.inner, name)

    @property
    def last_prompt_chars_before(self) -> int:
        return getattr(self, "_last_prompt_chars_before", 0)

    @property
    def last_prompt_chars_after(self) -> int:
        return getattr(self, "_last_prompt_chars_after", 0)

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        return self.inner.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        before = [dict(message) for message in messages]
        active = compact_tool_context(
            before,
            recent_messages=self.recent_messages,
            max_tool_chars=self.max_tool_chars,
        )

        self.calls += 1
        before_chars = _prompt_chars(before)
        after_chars = _prompt_chars(active)
        self._last_prompt_chars_before = before_chars
        self._last_prompt_chars_after = after_chars
        self.max_prompt_chars_before = max(self.max_prompt_chars_before, before_chars)
        self.max_prompt_chars_after = max(self.max_prompt_chars_after, after_chars)
        self.max_input_messages_before = max(self.max_input_messages_before, len(before))
        self.max_input_messages_after = max(self.max_input_messages_after, len(active))
        compacted = active != before
        if compacted:
            self.compaction_count += 1
        self.compaction_events.append(
            {
                "call_index": self.calls,
                "compacted": compacted,
                "prompt_chars_before": before_chars,
                "prompt_chars_after": after_chars,
                "messages_before": len(before),
                "messages_after": len(active),
            }
        )

        return self.inner.generate_with_tools(
            active,
            tools=tools,
            tool_choice=tool_choice,
        )


def _prompt_chars(messages: list[dict[str, Any]]) -> int:
    return sum(
        len(content)
        for message in messages
        if isinstance(message, dict)
        for content in [message.get("content")]
        if isinstance(content, str)
    )
