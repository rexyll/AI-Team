from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


# Only tools whose execution is observational and workspace-read-only may be
# considered for a safe batch. Mutating, execution, and persistence operations
# remain sequential by construction.
SAFE_BATCH_TOOLS = frozenset({"read_file", "list_files"})


@dataclass(frozen=True)
class ToolBatchDecision:
    """Decision describing whether a set of tool calls may share one batch."""

    safe: bool
    reason: str


def classify_safe_tool_batch(calls: Iterable[dict[str, Any]]) -> ToolBatchDecision:
    """Classify a model-emitted tool-call set conservatively.

    A batch is safe only when it contains at least two calls and every call is
    a known read-only filesystem observation. Unknown tools, malformed calls,
    and any mutating/execution tool reject the whole batch. This function does
    not execute or reorder calls; callers remain responsible for preserving
    tool-call order and dependency semantics.
    """
    items = list(calls)
    if len(items) < 2:
        return ToolBatchDecision(False, "batch requires at least two tool calls")

    for index, call in enumerate(items):
        if not isinstance(call, dict):
            return ToolBatchDecision(False, f"call {index} is not a mapping")
        name = call.get("name")
        if name not in SAFE_BATCH_TOOLS:
            return ToolBatchDecision(False, f"tool {name!r} is not safe for batching")
        arguments = call.get("arguments")
        if not isinstance(arguments, dict):
            return ToolBatchDecision(False, f"call {index} has malformed arguments")

    return ToolBatchDecision(True, "all calls are independent read-only filesystem observations")
