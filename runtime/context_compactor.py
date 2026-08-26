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
    """Return a bounded LLM context while preserving the task request.

    The persisted ToolExecutionHistory remains untouched. This helper only
    controls what is sent to the next LLM call. System and initial user
    messages are preserved; recent interaction messages are retained, while
    older tool outputs are summarized by a deterministic placeholder.
    """
    if recent_messages < 1:
        raise ValueError("recent_messages must be >= 1")
    if max_tool_chars < 1:
        raise ValueError("max_tool_chars must be >= 1")

    source = [dict(message) for message in messages]
    if len(source) <= recent_messages + 2:
        return source

    prefix: list[dict[str, Any]] = []
    for message in source[:2]:
        prefix.append(dict(message))

    tail = source[-recent_messages:]
    retained = {id(message) for message in tail}
    compacted: list[dict[str, Any]] = []

    for message in source[2:-recent_messages]:
        if message.get("role") != "tool":
            continue
        content = str(message.get("content", ""))
        compacted.append(
            {
                "role": "system",
                "content": (
                    "[Earlier tool result omitted from active context; "
                    f"original_chars={len(content)}]"
                ),
            }
        )
        if len(compacted) >= 1:
            break

    result = prefix + compacted + [dict(message) for message in tail]

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
