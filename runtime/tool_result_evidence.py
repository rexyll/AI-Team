from __future__ import annotations

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


def reduce_tool_result(tool_name: str, result: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> ToolEvidence:
    """Create bounded, decision-useful evidence without changing tool semantics.

    File reads keep both the beginning and end because imports/definitions tend
    to be near the start while diagnostics or generated content often ends with
    the relevant information. Test/command output keeps the tail, where failure
    summaries and assertion details normally occur. Structured results are first
    rendered as deterministic JSON-ish Python text and then bounded.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    text = str(result)
    original_chars = len(text)
    if original_chars <= max_chars:
        return ToolEvidence(text, original_chars, original_chars, False)

    if tool_name == "read_file":
        limit = min(max_chars, FILE_MAX_CHARS)
        head = max(1, int(limit * 0.65))
        tail = max(1, limit - head)
        content = text[:head] + "\n...[tool evidence truncated]...\n" + text[-tail:]
    elif tool_name == "run_command":
        limit = min(max_chars, TEST_MAX_CHARS)
        content = "...[tool evidence truncated; showing command tail]...\n" + text[-(limit - 52):]
    else:
        content = "...[tool evidence truncated]...\n" + text[-(max_chars - 34):]

    return ToolEvidence(content, original_chars, len(content), True)
