from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .tool_loop_classification import classify_tool_call_category
from .tool_result_evidence import reduce_tool_result


@dataclass(frozen=True)
class ToolCallTelemetry:
    """Derived facts used to measure tool-loop efficiency."""

    arguments_hash: str
    result_hash: str
    result_chars: int
    retained_result_chars: int
    result_truncated: bool
    duplicate_of: str | None = None
    retry_of: str | None = None
    category: str = "other"


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify_tool_call(*, tool_name: str, arguments: dict[str, Any], result: Any, prior: list[tuple[str, str, str, str]]) -> ToolCallTelemetry:
    """Classify a call against prior calls without changing tool execution semantics.

    ``prior`` entries are ``(execution_id, tool_name, arguments_hash, status)``.
    A duplicate has the same tool and arguments as an earlier call. A retry is a
    duplicate whose earlier matching call did not complete successfully.

    Evidence metrics are derived from the same bounded representation that is
    sent back to the LLM, so telemetry can distinguish raw result size from
    prompt-facing evidence size without changing the original tool result.
    """
    arguments_hash = stable_hash(arguments)
    result_hash = stable_hash(result)
    duplicate_of: str | None = None
    retry_of: str | None = None
    for execution_id, previous_tool, previous_arguments_hash, previous_status in reversed(prior):
        if previous_tool == tool_name and previous_arguments_hash == arguments_hash:
            duplicate_of = execution_id
            if previous_status != "completed":
                retry_of = execution_id
            break
    category = classify_tool_call_category(
        tool_name=tool_name,
        arguments=arguments,
        duplicate_of=duplicate_of,
        retry_of=retry_of,
    )
    evidence = reduce_tool_result(tool_name, result)
    return ToolCallTelemetry(
        arguments_hash=arguments_hash,
        result_hash=result_hash,
        result_chars=len(str(result)),
        retained_result_chars=evidence.retained_chars,
        result_truncated=evidence.truncated,
        duplicate_of=duplicate_of,
        retry_of=retry_of,
        category=category,
    )
