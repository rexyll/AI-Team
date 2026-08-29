from __future__ import annotations

from typing import Any

from runtime.tool_invocation_service import ToolInvocationService
from runtime.tool_result import ToolResult


class DeveloperToolInvocationAdapter:
    """Compatibility adapter for migrating DeveloperAgent's tool loop.

    The adapter deliberately owns only the execution boundary. DeveloperAgent
    keeps cache, verification-reuse, progress-guard, checkpoint and telemetry
    decisions outside this object; only an actual tool execution reaches the
    invocation service.
    """

    def __init__(self, service: ToolInvocationService) -> None:
        self._service = service

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
