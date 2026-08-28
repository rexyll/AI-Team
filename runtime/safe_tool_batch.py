from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SAFE_BATCH_TOOLS = frozenset({"list_files", "read_file"})


@dataclass(frozen=True)
class SafeToolBatchDecision:
    safe: bool
    reason: str


def classify_safe_tool_batch(tool_calls: list[dict[str, Any]]) -> SafeToolBatchDecision:
    """Conservatively classify whether tool calls may execute as one read batch.

    Only explicitly read-only tools are eligible. Unknown tools, mutation tools,
    commands, and duplicate targets are rejected so the caller can preserve the
    existing serial semantics.
    """
    if not tool_calls:
        return SafeToolBatchDecision(False, "empty_batch")

    names = [call.get("name") for call in tool_calls if isinstance(call, dict)]
    if len(names) != len(tool_calls):
        return SafeToolBatchDecision(False, "invalid_tool_call_shape")
    if any(name not in SAFE_BATCH_TOOLS for name in names):
        return SafeToolBatchDecision(False, "contains_non_read_only_tool")

    identities: set[tuple[str, str]] = set()
    for call in tool_calls:
        name = call.get("name")
        arguments = call.get("arguments")
        if not isinstance(arguments, dict):
            return SafeToolBatchDecision(False, "invalid_arguments")
        identity = (str(name), repr(sorted(arguments.items())))
        if identity in identities:
            return SafeToolBatchDecision(False, "duplicate_read_only_call")
        identities.add(identity)

    # A list_files result can change what a subsequent read_file should target;
    # callers must therefore not infer cross-call independence from tool names.
    # Batch is reserved for independently-addressed read_file calls or
    # independently-addressed list_files calls.
    if len(tool_calls) > 1:
        if any(call.get("name") == "list_files" for call in tool_calls):
            if len({call.get("name") for call in tool_calls}) > 1:
                return SafeToolBatchDecision(False, "cross_tool_dependency_possible")

    return SafeToolBatchDecision(True, "independent_read_only_calls")
