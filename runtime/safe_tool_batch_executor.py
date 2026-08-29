from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from runtime.safe_tool_batch import SafeToolBatchDecision, classify_safe_tool_batch


ToolExecutor = Callable[..., Any]


def execute_safe_tool_batch(
    tool_calls: list[dict[str, Any]],
    executor: ToolExecutor,
    *,
    max_workers: int | None = None,
) -> tuple[SafeToolBatchDecision, list[Any]]:
    """Execute an already-classified safe read-only batch concurrently.

    Results are returned in the exact same order as ``tool_calls`` regardless
    of completion order. Unsafe batches are never executed by this helper.

    A batch entry may optionally provide ``execution_id``. Executors that
    accept a third positional argument receive that canonical identity;
    legacy two-argument executors remain supported for compatibility.
    """
    decision = classify_safe_tool_batch(tool_calls)
    if not decision.safe:
        return decision, []

    workers = max_workers or len(tool_calls)
    workers = max(1, min(workers, len(tool_calls)))

    try:
        parameters = list(inspect.signature(executor).parameters.values())
        accepts_three = any(
            parameter.kind == inspect.Parameter.VAR_POSITIONAL
            for parameter in parameters
        ) or len(parameters) >= 3
    except (TypeError, ValueError):
        accepts_three = False

    def run_one(call: dict[str, Any]) -> Any:
        name = str(call["name"])
        arguments = dict(call["arguments"])
        execution_id = call.get("execution_id")
        if accepts_three and execution_id is not None:
            return executor(name, arguments, str(execution_id))
        return executor(name, arguments)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, call) for call in tool_calls]
        results = [future.result() for future in futures]
    return decision, results
