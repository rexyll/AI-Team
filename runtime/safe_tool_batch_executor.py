from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from runtime.safe_tool_batch import SafeToolBatchDecision, classify_safe_tool_batch


ToolExecutor = Callable[[str, dict[str, Any]], Any]


def execute_safe_tool_batch(
    tool_calls: list[dict[str, Any]],
    executor: ToolExecutor,
    *,
    max_workers: int | None = None,
) -> tuple[SafeToolBatchDecision, list[Any]]:
    """Execute an already-classified safe read-only batch concurrently.

    Results are returned in the exact same order as ``tool_calls`` regardless
    of completion order. Unsafe batches are never executed by this helper.
    """
    decision = classify_safe_tool_batch(tool_calls)
    if not decision.safe:
        return decision, []

    workers = max_workers or len(tool_calls)
    workers = max(1, min(workers, len(tool_calls)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(executor, str(call["name"]), dict(call["arguments"]))
            for call in tool_calls
        ]
        # Reading futures in submission order deliberately preserves the LLM
        # tool-call ordering required by execution history and telemetry.
        results = [future.result() for future in futures]
    return decision, results
