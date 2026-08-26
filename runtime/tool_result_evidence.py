from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolEvidence:
    """Bounded evidence sent back into the LLM context.

    The original tool result remains available to execution history/telemetry;
    this object is only the context representation used for the next decision.
    """

    content: str
    original_chars: int
    retained_chars: int
    truncated: bool


DEFAULT_MAX_CHARS = 8_000
TEST_MAX_CHARS = 6_000
FILE_MAX_CHARS = 7_000


def _render_result(result: Any) -> str:
    """Render structured tool results deterministically before budgeting."""
    if isinstance(result, (dict, list, tuple)):
        try:
            return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            pass
    return str(result)


def _tail_with_marker(text: str, marker: str, limit: int) -> str:
    """Return at most ``limit`` characters while preserving the marker."""
    if limit <= len(marker):
        return marker[:limit]
    return marker + text[-(limit - len(marker)):]


def reduce_tool_result(tool_name: str, result: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> ToolEvidence:
    """Create bounded, decision-useful evidence without changing tool semantics.

    File reads keep both the beginning and end because imports/definitions tend
    to be near the start while diagnostics or generated content often ends with
    the relevant information. Test/command output keeps the tail, where failure
    summaries and assertion details normally occur. Structured results are
    rendered deterministically before they are budgeted.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    text = _render_result(result)
    original_chars = len(text)
    if original_chars <= max_chars:
        return ToolEvidence(text, original_chars, original_chars, False)

    if tool_name == "read_file":
        limit = min(max_chars, FILE_MAX_CHARS)
        marker = "\n...[tool evidence truncated]...\n"
        if limit <= len(marker):
            content = marker[:limit]
        else:
            payload = limit - len(marker)
            head = max(1, int(payload * 0.65))
            tail = max(1, payload - head)
            content = text[:head] + marker + text[-tail:]
    elif tool_name == "run_command":
        limit = min(max_chars, TEST_MAX_CHARS)
        content = _tail_with_marker(
            text,
            "...[tool evidence truncated; showing command tail]...\n",
            limit,
        )
    else:
        content = _tail_with_marker(text, "...[tool evidence truncated]...\n", max_chars)

    return ToolEvidence(content, original_chars, len(content), True)
