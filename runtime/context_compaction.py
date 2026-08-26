from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_MAX_PROMPT_CHARS = 24000
DEFAULT_MAX_INPUT_TOKENS_PER_CALL = 12000
TRUNCATION_MARKER = "\n...[context compacted: {removed} chars]...\n"


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def estimate_tokens(text: str) -> int:
    """Conservatively estimate input tokens without adding a tokenizer dependency.

    ASCII-heavy code/JSON is estimated at roughly four characters per token;
    non-ASCII text is counted more conservatively because CJK text generally
    has a higher token-to-character ratio. This is an operational guard, not
    a provider billing/tokenization oracle.
    """
    if not isinstance(text, str) or not text:
        return 0

    ascii_chars = sum(ord(char) < 128 for char in text)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, (ascii_chars + 3) // 4 + (non_ascii_chars + 1) // 2)


def _render_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False, default=str)


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text

    marker = TRUNCATION_MARKER.format(removed=len(text) - limit)
    if len(marker) >= limit:
        return text[:limit]

    head = (limit - len(marker)) // 2
    tail = limit - len(marker) - head
    return text[:head] + marker + text[-tail:]


@dataclass(frozen=True)
class CompactionStats:
    original_chars: int
    compacted_chars: int
    original_tokens: int
    compacted_tokens: int
    truncated_messages: int

    @property
    def growth_ratio(self) -> float:
        if self.original_chars <= 0:
            return 1.0
        return self.compacted_chars / self.original_chars


@dataclass(frozen=True)
class ContextCompactionConfig:
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS
    max_input_tokens_per_call: int = DEFAULT_MAX_INPUT_TOKENS_PER_CALL

    @classmethod
    def from_env(cls) -> "ContextCompactionConfig":
        return cls(
            max_prompt_chars=_positive_env_int(
                "AI_TEAM_MAX_PROMPT_CHARS",
                DEFAULT_MAX_PROMPT_CHARS,
            ),
            max_input_tokens_per_call=_positive_env_int(
                "AI_TEAM_MAX_INPUT_TOKENS_PER_CALL",
                DEFAULT_MAX_INPUT_TOKENS_PER_CALL,
            ),
        )


class ContextCompactor:
    """Bound LLM conversation context while preserving tool-call structure."""

    def __init__(self, config: ContextCompactionConfig | None = None) -> None:
        self.config = config or ContextCompactionConfig.from_env()
        if self.config.max_prompt_chars <= 0:
            raise ValueError("max_prompt_chars must be > 0")
        if self.config.max_input_tokens_per_call <= 0:
            raise ValueError("max_input_tokens_per_call must be > 0")

    def compact_messages(
        self,
        messages: Iterable[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], CompactionStats]:
        source = [deepcopy(message) for message in messages]
        if not all(isinstance(message, dict) for message in source):
            raise TypeError("messages must contain dictionaries")

        original_chars = self._total_chars(source)
        original_tokens = self._total_tokens(source)
        compacted = source
        truncated_messages: set[int] = set()

        # Keep system instructions intact and prefer preserving recent turns.
        # Older tool outputs are the first compaction candidates because they
        # are usually the largest and least useful once newer evidence exists.
        candidates = self._candidate_indexes(compacted)
        for index in candidates:
            if self._within_budget(compacted):
                break

            current = _render_message_content(compacted[index].get("content"))
            if not current:
                continue

            minimum = self._minimum_content_length(compacted[index].get("role"))
            target = min(len(current), max(minimum, len(current) // 2))
            target = self._fit_text_to_budget(compacted, index, current, target)
            if target < len(current):
                compacted[index]["content"] = _truncate_text(current, target)
                truncated_messages.add(index)

        # A final global pass guarantees the configured character/token guard
        # whenever compaction is possible without touching system messages.
        for index in candidates:
            if self._within_budget(compacted):
                break
            current = _render_message_content(compacted[index].get("content"))
            if not current:
                continue
            minimum = 0 if compacted[index].get("role") == "tool" else 64
            target = self._fit_text_to_budget(compacted, index, current, minimum)
            if target < len(current):
                compacted[index]["content"] = _truncate_text(current, target)
                truncated_messages.add(index)

        compacted_chars = self._total_chars(compacted)
        compacted_tokens = self._total_tokens(compacted)
        return compacted, CompactionStats(
            original_chars=original_chars,
            compacted_chars=compacted_chars,
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            truncated_messages=len(truncated_messages),
        )

    def compact_prompt(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
    ) -> tuple[str, str, CompactionStats]:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string")
        if not isinstance(system_prompt, str):
            raise TypeError("system_prompt must be a string")

        messages, stats = self.compact_messages(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
        )
        return messages[1]["content"], messages[0]["content"], stats

    def _within_budget(self, messages: list[dict[str, Any]]) -> bool:
        return (
            self._total_chars(messages) <= self.config.max_prompt_chars
            and self._total_tokens(messages) <= self.config.max_input_tokens_per_call
        )

    @staticmethod
    def _candidate_indexes(messages: list[dict[str, Any]]) -> list[int]:
        ranked: list[tuple[int, int]] = []
        last_user = max(
            (index for index, message in enumerate(messages) if message.get("role") == "user"),
            default=-1,
        )
        for index, message in enumerate(messages):
            role = message.get("role")
            if role == "system":
                continue
            if role == "tool":
                priority = 0
            elif role == "assistant":
                priority = 1
            elif role == "user":
                priority = 2 if index != last_user else 4
            else:
                priority = 1
            ranked.append((priority, index))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [index for _, index in ranked]

    @staticmethod
    def _minimum_content_length(role: Any) -> int:
        if role == "tool":
            return 128
        if role == "assistant":
            return 256
        return 512

    def _fit_text_to_budget(
        self,
        messages: list[dict[str, Any]],
        index: int,
        current: str,
        upper: int,
    ) -> int:
        if not current:
            return 0
        upper = max(0, min(len(current), upper))
        low = 0
        high = upper
        best = 0
        original = messages[index].get("content")

        while low <= high:
            middle = (low + high) // 2
            messages[index]["content"] = _truncate_text(current, middle)
            if self._within_budget(messages):
                best = middle
                low = middle + 1
            else:
                high = middle - 1

        messages[index]["content"] = original
        return best

    @staticmethod
    def _total_chars(messages: list[dict[str, Any]]) -> int:
        return sum(len(_render_message_content(message.get("content"))) for message in messages)

    @staticmethod
    def _total_tokens(messages: list[dict[str, Any]]) -> int:
        return sum(
            estimate_tokens(_render_message_content(message.get("content")))
            for message in messages
        )
