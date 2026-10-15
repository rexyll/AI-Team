from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from security.runtime_capability import DEFAULT_RUNTIME_CAPABILITY_POLICY, RuntimeCapabilityPolicy
from security.tool_permission import ToolPermissionError, ToolPermissionPolicy
from security.tool_guard import ToolArgumentValidationError, validate_tool_arguments
from runtime.tool_errors import ToolError, classify_tool_exception
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
from runtime.tool_invocation import ToolInvocation
from runtime.tool_result import ToolResult
from runtime.tracing import DEFAULT_TRACER
from tools.registry import TOOL_REGISTRY, ToolRegistry


class ToolInvocationService:
    """Single runtime boundary for authorized tool invocation."""

    def __init__(self, *, registry: ToolRegistry | None = None, capability_policy: RuntimeCapabilityPolicy | None = None, permission_policy: ToolPermissionPolicy | None = None, history: ToolExecutionHistory | None = None) -> None:
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

    def invoke(self, *, role: str, task_id: str, execution_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        request = ToolInvocation(role=role, task_id=task_id, execution_id=execution_id, tool_name=tool_name, arguments=arguments)
        return self.invoke_request(request)

    def invoke_request(self, request: ToolInvocation) -> ToolResult:
        """Authorize, validate, execute, and record one canonical request."""
        if not isinstance(request, ToolInvocation):
            raise TypeError("request must be a ToolInvocation")
        started_at = datetime.now(timezone.utc).isoformat()
        record_arguments = request.as_dict()
        try:
            tool_function = self._registry.get(request.tool_name)
            tool_schema = self._registry.schema(request.tool_name)
            self._capability_policy.require(request.role, request.tool_name)
            if self._permission_policy is not None:
                for capability in self._capability_policy.required_capabilities(request.tool_name):
                    self._permission_policy.require(request.tool_name, capability)
            validated, _ = validate_tool_arguments(tool_function, request.as_dict(), schema=tool_schema)
            record_arguments = dict(validated)
        except (KeyError, ToolPermissionError, ToolArgumentValidationError, TypeError, ValueError) as exc:
            error = self._classify_boundary_error(exc)
            status = "invalid_arguments" if error.category == "argument_validation" else "failed"
            self._append_record(execution_id=request.execution_id, task_id=request.task_id, role=request.role, tool_name=request.tool_name, started_at=started_at, status=status, arguments=record_arguments, output=None, error=error)
            return ToolResult.fail(error)
        try:
            with DEFAULT_TRACER.span(
                "tool.invoke",
                attributes={
                    "task_id": request.task_id,
                    "agent_role": request.role,
                    "tool_name": request.tool_name,
                    "execution_id": request.execution_id,
                },
            ) as span:
                output = tool_function(**record_arguments)
                span.set_attribute("status", "completed")
        except Exception as exc:
            error = self._classify_boundary_error(exc)
            self._append_record(execution_id=request.execution_id, task_id=request.task_id, role=request.role, tool_name=request.tool_name, started_at=started_at, status="failed", arguments=record_arguments, output=None, error=error)
            return ToolResult.fail(error)
        self._append_record(execution_id=request.execution_id, task_id=request.task_id, role=request.role, tool_name=request.tool_name, started_at=started_at, status="completed", arguments=record_arguments, output=output, error=None)
        return ToolResult.ok(output)

    def invoke_many(self, *, role: str, task_id: str, invocations: list[dict[str, Any]]) -> list[ToolResult]:
        requests = self._build_requests(role=role, task_id=task_id, invocations=invocations)
        return [self.invoke_request(request) for request in requests]

    def invoke_many_concurrent(self, *, role: str, task_id: str, invocations: list[dict[str, Any]], max_workers: int | None = None) -> list[ToolResult]:
        """Run independent calls concurrently while every call remains audited."""
        requests = self._build_requests(role=role, task_id=task_id, invocations=invocations)
        if not requests:
            return []
        workers = max_workers or len(requests)
        workers = max(1, min(workers, len(requests)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self.invoke_request, request) for request in requests]
            return [future.result() for future in futures]

    @staticmethod
    def _build_requests(*, role: str, task_id: str, invocations: list[dict[str, Any]]) -> list[ToolInvocation]:
        if not isinstance(invocations, list):
            raise TypeError("invocations must be a list")
        requests: list[ToolInvocation] = []
        seen: set[str] = set()
        for invocation in invocations:
            request = ToolInvocation.from_dict(invocation, role=role, task_id=task_id)
            if request.execution_id in seen:
                raise ValueError(f"duplicate execution_id in invocation batch: {request.execution_id}")
            seen.add(request.execution_id)
            requests.append(request)
        return requests

    def _append_record(self, *, execution_id: str, task_id: str, role: str, tool_name: str, started_at: str, status: str, arguments: dict[str, Any], output: Any, error: ToolError | None) -> None:
        record = ToolExecutionRecord(execution_id=execution_id, task_id=task_id, agent_role=role, tool_name=tool_name, started_at=started_at, completed_at=datetime.now(timezone.utc).isoformat(), status=status, arguments=arguments, output=output if status == "completed" else None, error=error.to_dict() if error is not None else None)
        try:
            self._history.append(record)
        except ValueError:
            # Resumed attempts (gate retries) reload a persisted history and
            # can legitimately reuse model-generated call ids. The execution
            # happened and must stay audited: keep the record under a
            # disambiguated id instead of failing the invocation.
            suffix = 2
            while True:
                try:
                    self._history.append(replace(record, execution_id=f"{execution_id}#{suffix}"))
                    return
                except ValueError:
                    suffix += 1

    @staticmethod
    def _classify_boundary_error(exc: BaseException) -> ToolError:
        if isinstance(exc, KeyError):
            return ToolError("TOOL_UNKNOWN", "unknown", "Unknown tool")
        return classify_tool_exception(exc)
