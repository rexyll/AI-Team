from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.tool_loop_batch import SAFE_BATCH_TOOLS


@dataclass(frozen=True)
class SafeToolBatchDecision:
    safe: bool
    reason: str


def classify_safe_tool_batch(tool_calls: list[dict[str, Any]]) -> SafeToolBatchDecision:
    """Conservatively classify a candidate batch for Developer execution.

    The repository already defines the public safe-batch allowlist in
    ``runtime.tool_loop_batch``. This adapter adds the execution-layer rule
    that exact duplicate read-only calls are not a batch: they belong to the
    existing cache/deduplication path. All other read-only calls remain
    eligible and are never reordered here.
    """
    if len(tool_calls) < 2:
        return SafeToolBatchDecision(False, "batch requires at least two tool calls")

    identities: set[tuple[str, str]] = set()
    for index, call in enumerate(tool_calls):
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
