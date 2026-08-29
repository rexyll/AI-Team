from __future__ import annotations

from typing import Any

import pytest

from runtime.tool_invocation_service import ToolInvocationService
from runtime.tool_errors import ToolExecutionError
from security.runtime_capability import RuntimeCapabilityPolicy
from security.tool_permission import ToolPermissionPolicy
from tools.registry import ToolRegistry


def _registry(calls: list[dict[str, Any]]) -> ToolRegistry:
    registry = ToolRegistry()

    def fake_read_file(path: str) -> str:
        calls.append({"path": path})
        return f"content:{path}"

    registry.register(
        "read_file",
        fake_read_file,
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "test read",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
    )
    return registry


def test_authorized_invocation_executes_and_audits() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))

    result = service.invoke(
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-001",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
    )

    assert result.success is True
    assert result.output == "content:src/app.py"
    assert calls == [{"path": "src/app.py"}]
    records = service.audit.records()
    assert len(records) == 1
    assert records[0].execution_id == "EXEC-001"
    assert records[0].status == "completed"


def test_read_capability_is_allowed_for_reviewer() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))

    result = service.invoke(
        role="reviewer",
        task_id="TASK-001",
        execution_id="EXEC-002",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
    )

    assert result.success is True
    assert calls == [{"path": "src/app.py"}]


def test_write_capability_is_denied_for_reviewer() -> None:
    calls: list[dict[str, Any]] = []
    registry = ToolRegistry()

    def fake_write_file(path: str, content: str) -> None:
        calls.append({"path": path, "content": content})

    registry.register(
        "write_file",
        fake_write_file,
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "test write",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
    )
    service = ToolInvocationService(registry=registry)

    result = service.invoke(
        role="reviewer",
        task_id="TASK-001",
        execution_id="EXEC-003",
        tool_name="write_file",
        arguments={"path": "src/app.py", "content": "x"},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "permission"
    assert calls == []
    assert service.audit.count(status="failed") == 1


def test_schema_validation_happens_before_tool_execution() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))

    result = service.invoke(
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-004",
        tool_name="read_file",
        arguments={"path": 123},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "argument_validation"
    assert calls == []
    record = service.audit.records()[0]
    assert record.status == "invalid_arguments"


def test_optional_tool_permission_policy_can_add_second_deny_boundary() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(
        registry=_registry(calls),
        capability_policy=RuntimeCapabilityPolicy(),
        permission_policy=ToolPermissionPolicy({"read_file": {}}),
    )

    result = service.invoke(
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-005",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "permission"
    assert calls == []


def test_tool_exception_is_classified_and_audited() -> None:
    calls: list[dict[str, Any]] = []
    registry = ToolRegistry()

    def failing_tool(path: str) -> str:
        calls.append({"path": path})
        raise ToolExecutionError("internal failure")

    registry.register(
        "read_file",
        failing_tool,
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "test failure",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
    )
    service = ToolInvocationService(registry=registry)

    result = service.invoke(
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-006",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_EXECUTION_FAILED"
    assert result.error.category == "runtime"
    assert service.audit.records()[0].error == result.error.to_dict()
    assert calls == [{"path": "src/app.py"}]
