from __future__ import annotations

from typing import Any

from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_invocation_service import ToolInvocationService
from runtime.tool_result import ToolResult


class DeveloperToolInvocationAdapter:
    """Compatibility adapter for migrating DeveloperAgent's tool loop.

    The adapter deliberately owns only the execution boundary. DeveloperAgent
    keeps cache, verification-reuse, progress-guard, checkpoint and telemetry
    decisions outside this object; only an actual tool execution reaches the
    invocation service.

    ``history`` remains a supported constructor argument because DeveloperAgent
    owns the task-scoped history lifecycle.  When supplied, the adapter creates
    the invocation service around that exact history object so audit/history
    records remain canonical and immediately visible to the caller.
    """

    def __init__(
        self,
        service: ToolInvocationService | None = None,
        *,
        history: ToolExecutionHistory | None = None,
    ) -> None:
        if service is not None and history is not None:
            raise ValueError("provide either service or history, not both")
        if service is not None:
            if not isinstance(service, ToolInvocationService):
                raise TypeError("service must be a ToolInvocationService or None")
            self._service = service
        else:
            if history is not None and not isinstance(history, ToolExecutionHistory):
                raise TypeError("history must be a ToolExecutionHistory or None")
            self._service = ToolInvocationService(history=history)

    @property
    def history(self) -> ToolExecutionHistory:
        return self._service.history

    @property
    def audit(self):
        return self._service.audit

    def invoke(
        self,
        *,
        task_id: str,
        execution_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        return self._service.invoke(
            role="developer",
            task_id=task_id,
            execution_id=execution_id,
            tool_name=tool_name,
            arguments=arguments,
        )

    def invoke_many(
        self,
        *,
        task_id: str,
        invocations: list[dict[str, Any]],
    ) -> list[ToolResult]:
        return self._service.invoke_many(
            role="developer",
            task_id=task_id,
            invocations=invocations,
        )

    def invoke_many_concurrent(
        self,
        *,
        task_id: str,
        invocations: list[dict[str, Any]],
        max_workers: int | None = None,
    ) -> list[ToolResult]:
        return self._service.invoke_many_concurrent(
            role="developer",
            task_id=task_id,
            invocations=invocations,
            max_workers=max_workers,
        )
