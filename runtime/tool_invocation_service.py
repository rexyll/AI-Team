from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from security.runtime_capability import (
    DEFAULT_RUNTIME_CAPABILITY_POLICY,
    RuntimeCapabilityPolicy,
)
from security.tool_permission import ToolPermissionError, ToolPermissionPolicy
from security.tool_guard import ToolArgumentValidationError, validate_tool_arguments
from runtime.tool_errors import ToolError, classify_tool_exception
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
from runtime.tool_result import ToolResult
from tools.registry import TOOL_REGISTRY, ToolRegistry


class ToolInvocationService:
    """Single runtime boundary for authorized tool invocation."""

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        capability_policy: RuntimeCapabilityPolicy | None = None,
        permission_policy: ToolPermissionPolicy | None = None,
        history: ToolExecutionHistory | None = None,
    ) -> None:
        if registry is not None and not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry or None")
        if capability_policy is not None and not isinstance(capability_policy, RuntimeCapabilityPolicy):
            raise TypeError("capability_policy must be a RuntimeCapabilityPolicy or None")
        if permission_policy is not None and not isinstance(permission_policy, ToolPermissionPolicy):
            raise TypeError("permission_policy must be a ToolPermissionPolicy or None")
        if history is not None and not isinstance(history, ToolExecutionHistory):
            raise TypeError("history must be a ToolExecutionHistory or None")

        self._registry = registry or TOOL_REGISTRY
        self._capability_policy = capability_policy or DEFAULT_RUNTIME_CAPABILITY_POLICY
        self._permission_policy = permission_policy
        self._history = history or ToolExecutionHistory()

    @property
    def history(self) -> ToolExecutionHistory:
        return ToolExecutionHistory.from_dict(self._history.to_dict())

    @property
    def audit(self) -> ToolExecutionAudit:
        return ToolExecutionAudit(self._history)

    def invoke(
        self,
        *,
        role: str,
        task_id: str,
        execution_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Authorize, validate, execute, and record one tool invocation."""
        started_at = datetime.now(timezone.utc).isoformat()
        record_arguments: dict[str, Any] = dict(arguments) if isinstance(arguments, dict) else {}

        try:
            tool_function = self._registry.get(tool_name)
            tool_schema = self._registry.schema(tool_name)
            self._capability_policy.require(role, tool_name)
            if self._permission_policy is not None:
                for capability in self._capability_policy.required_capabilities(tool_name):
                    self._permission_policy.require(tool_name, capability)
            validated, _ = validate_tool_arguments(
                tool_function,
                arguments,
                schema=tool_schema,
            )
            record_arguments = dict(validated)
        except (KeyError, ToolPermissionError, ToolArgumentValidationError, TypeError, ValueError) as exc:
            error = self._classify_boundary_error(exc)
            status = "invalid_arguments" if error.category == "argument_validation" else "failed"
            self._append_record(
                execution_id=execution_id,
                task_id=task_id,
                role=role,
                tool_name=tool_name,
                started_at=started_at,
                status=status,
                arguments=record_arguments,
                output=None,
                error=error,
            )
            return ToolResult.fail(error)

        try:
            output = tool_function(**record_arguments)
        except Exception as exc:
            error = self._classify_boundary_error(exc)
            self._append_record(
                execution_id=execution_id,
                task_id=task_id,
                role=role,
                tool_name=tool_name,
                started_at=started_at,
                status="failed",
                arguments=record_arguments,
                output=None,
                error=error,
            )
            return ToolResult.fail(error)

        self._append_record(
            execution_id=execution_id,
            task_id=task_id,
            role=role,
            tool_name=tool_name,
            started_at=started_at,
            status="completed",
            arguments=record_arguments,
            output=output,
            error=None,
        )
        return ToolResult.ok(output)

    def invoke_many(
        self,
        *,
        role: str,
        task_id: str,
        invocations: list[dict[str, Any]],
    ) -> list[ToolResult]:
        """Invoke a sequence through the same authorization and audit boundary.

        This intentionally preserves per-invocation execution IDs and records. It
        is the migration-safe entry point for callers that currently batch tool
        calls; optimization of safe batches remains an implementation detail for
        a later phase and must not bypass authorization or audit.
        """
        results: list[ToolResult] = []
        for invocation in invocations:
            if not isinstance(invocation, dict):
                raise TypeError("each invocation must be a dictionary")
            required = {"execution_id", "tool_name", "arguments"}
            missing = required - invocation.keys()
            if missing:
                raise ValueError(
                    "invocation is missing required fields: "
                    + ", ".join(sorted(missing))
                )
            arguments = invocation["arguments"]
            if not isinstance(arguments, dict):
                raise TypeError("invocation arguments must be a dictionary")
            results.append(
                self.invoke(
                    role=role,
                    task_id=task_id,
                    execution_id=str(invocation["execution_id"]),
                    tool_name=str(invocation["tool_name"]),
                    arguments=arguments,
                )
            )
        return results

    def _append_record(
        self,
        *,
        execution_id: str,
        task_id: str,
        role: str,
        tool_name: str,
        started_at: str,
        status: str,
        arguments: dict[str, Any],
        output: Any,
        error: ToolError | None,
    ) -> None:
        self._history.append(
            ToolExecutionRecord(
                execution_id=execution_id,
                task_id=task_id,
                agent_role=role,
                tool_name=tool_name,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                status=status,
                arguments=arguments,
                output=output if status == "completed" else None,
                error=error.to_dict() if error is not None else None,
            )
        )

    @staticmethod
    def _classify_boundary_error(exc: BaseException) -> ToolError:
        if isinstance(exc, KeyError):
            return ToolError("TOOL_UNKNOWN", "unknown", "Unknown tool")
        return classify_tool_exception(exc)
