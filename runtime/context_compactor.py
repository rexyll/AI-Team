from __future__ import annotations

from collections.abc import Iterable
from typing import Any


DEFAULT_RECENT_MESSAGES = 12
DEFAULT_MAX_TOOL_CHARS = 12_000


def compact_tool_context(
    messages: Iterable[dict[str, Any]],
    *,
    recent_messages: int = DEFAULT_RECENT_MESSAGES,
    max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
) -> list[dict[str, Any]]:
    """Return a bounded LLM context without mutating the source messages.

    The first system/user messages form the stable task contract. Older
    interaction messages are removed from the active context and represented
    by a compact deterministic summary marker. Recent messages are retained,
    and oversized retained tool outputs are truncated. Persisted execution
    history is deliberately not modified by this helper.
    """
    if recent_messages < 1:
        raise ValueError("recent_messages must be >= 1")
    if max_tool_chars < 1:
        raise ValueError("max_tool_chars must be >= 1")

    source = [dict(message) for message in messages]
    if len(source) <= recent_messages + 2:
        return _bounded_tool_outputs(source, max_tool_chars)

    prefix = [dict(message) for message in source[:2]]
    tail = [dict(message) for message in source[-recent_messages:]]

    older = source[2:-recent_messages]
    omitted_tools = sum(1 for message in older if message.get("role") == "tool")
    omitted_messages = len(older)

    compacted: list[dict[str, Any]] = []
    if omitted_messages:
        compacted.append(
            {
                "role": "system",
                "content": f"[compacted: {omitted_messages} msgs, {omitted_tools} tools]",
            }
        )

    return _bounded_tool_outputs(prefix + compacted + tail, max_tool_chars)


def _bounded_tool_outputs(
    messages: list[dict[str, Any]],
    max_tool_chars: int,
) -> list[dict[str, Any]]:
    result = [dict(message) for message in messages]
    for message in result:
        if message.get("role") != "tool":
            continue
        content = str(message.get("content", ""))
        if len(content) > max_tool_chars:
            message["content"] = (
                content[:max_tool_chars]
                + f"\n[tool output truncated; original_chars={len(content)}]"
            )
    return result
