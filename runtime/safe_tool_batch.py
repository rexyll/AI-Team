from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from runtime.tool_loop_batch import SAFE_BATCH_TOOLS


@dataclass(frozen=True)
class SafeToolBatchDecision:
    safe: bool
    reason: str


def classify_safe_tool_batch(tool_calls: Iterable[dict[str, Any]]) -> SafeToolBatchDecision:
    """Compatibility facade over the canonical safe-batch policy.

    ``runtime.tool_loop_batch`` owns the public allowlist. This adapter keeps
    the execution-layer API while adding only the duplicate-call rule so
    duplicate reads remain handled by the existing cache/dedup path.
    """
    items = list(tool_calls)
    if len(items) < 2:
        return SafeToolBatchDecision(False, "batch requires at least two tool calls")

    identities: set[tuple[str, str]] = set()
    for index, call in enumerate(items):
        if not isinstance(call, dict):
            return SafeToolBatchDecision(False, f"call {index} is not a mapping")
        name = call.get("name")
        if name not in SAFE_BATCH_TOOLS:
            return SafeToolBatchDecision(False, f"tool {name!r} is not safe for batching")
        arguments = call.get("arguments")
        if not isinstance(arguments, dict):
            return SafeToolBatchDecision(False, f"call {index} has malformed arguments")
        identity = (str(name), repr(sorted(arguments.items())))
        if identity in identities:
            return SafeToolBatchDecision(False, "duplicate_read_only_call")
        identities.add(identity)

    return SafeToolBatchDecision(True, "independent_read_only_calls")
