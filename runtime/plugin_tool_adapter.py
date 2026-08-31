from __future__ import annotations

from typing import Any

from runtime.tool_invocation_service import ToolInvocationService
from runtime.tool_result import ToolResult


class PluginToolInvocationAdapter:
    """Narrow plugin-facing tool boundary backed by the canonical runtime service.

    The plugin receives a fixed trusted role at construction time. It cannot
    supply or override the runtime role, access the tool registry, or bypass
    capability / permission / argument-validation / audit / tracing checks.
    """

    def __init__(self, service: ToolInvocationService, *, role: str) -> None:
        if not isinstance(service, ToolInvocationService):
            raise TypeError("service must be a ToolInvocationService")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role must be a non-empty string")
        self._service = service
        self._role = role

    @property
    def role(self) -> str:
        """Return the host-assigned authorization role."""
        return self._role

    def invoke(
        self,
        *,
        task_id: str,
        execution_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Invoke one tool through the canonical runtime authorization boundary."""
        return self._service.invoke(
            role=self._role,
            task_id=task_id,
            execution_id=execution_id,
            tool_name=tool_name,
            arguments=arguments,
        )
