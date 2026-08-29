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
        "read_file", fake_read_file,
        {"type": "function", "function": {"name": "read_file", "description": "test read", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    )
    return registry


def test_authorized_invocation_executes_and_audits() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    result = service.invoke(role="developer", task_id="TASK-001", execution_id="EXEC-001", tool_name="read_file", arguments={"path": "src/app.py"})
    assert result.success is True
    assert result.output == "content:src/app.py"
    assert calls == [{"path": "src/app.py"}]
    assert service.audit.records()[0].execution_id == "EXEC-001"
    assert service.audit.records()[0].status == "completed"


def test_read_capability_is_allowed_for_reviewer() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    result = service.invoke(role="reviewer", task_id="TASK-001", execution_id="EXEC-002", tool_name="read_file", arguments={"path": "src/app.py"})
    assert result.success is True
    assert calls == [{"path": "src/app.py"}]


def test_write_capability_is_denied_for_reviewer() -> None:
    calls: list[dict[str, Any]] = []
    registry = ToolRegistry()
    def fake_write_file(path: str, content: str) -> None:
        calls.append({"path": path, "content": content})
    registry.register("write_file", fake_write_file, {"type": "function", "function": {"name": "write_file", "description": "test write", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}})
    service = ToolInvocationService(registry=registry)
    result = service.invoke(role="reviewer", task_id="TASK-001", execution_id="EXEC-003", tool_name="write_file", arguments={"path": "src/app.py", "content": "x"})
    assert result.success is False
    assert result.error is not None and result.error.category == "permission"
    assert calls == []
    assert service.audit.count(status="failed") == 1


def test_schema_validation_happens_before_tool_execution() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    result = service.invoke(role="developer", task_id="TASK-001", execution_id="EXEC-004", tool_name="read_file", arguments={"path": 123})
    assert result.success is False
    assert result.error is not None and result.error.category == "argument_validation"
    assert calls == []
    assert service.audit.records()[0].status == "invalid_arguments"


def test_optional_tool_permission_policy_can_add_second_deny_boundary() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls), capability_policy=RuntimeCapabilityPolicy(), permission_policy=ToolPermissionPolicy({"read_file": {}}))
    result = service.invoke(role="developer", task_id="TASK-001", execution_id="EXEC-005", tool_name="read_file", arguments={"path": "src/app.py"})
    assert result.success is False
    assert result.error is not None and result.error.category == "permission"
    assert calls == []


def test_tool_exception_is_classified_and_audited() -> None:
    calls: list[dict[str, Any]] = []
    registry = ToolRegistry()
    def failing_tool(path: str) -> str:
        calls.append({"path": path})
        raise ToolExecutionError("internal failure")
    registry.register("read_file", failing_tool, {"type": "function", "function": {"name": "read_file", "description": "test failure", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}})
    service = ToolInvocationService(registry=registry)
    result = service.invoke(role="developer", task_id="TASK-001", execution_id="EXEC-006", tool_name="read_file", arguments={"path": "src/app.py"})
    assert result.success is False
    assert result.error is not None and result.error.code == "TOOL_EXECUTION_FAILED" and result.error.category == "runtime"
    assert service.audit.records()[0].error == result.error.to_dict()
    assert calls == [{"path": "src/app.py"}]


def test_invoke_many_preserves_execution_ids_and_uses_one_boundary() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    results = service.invoke_many(role="developer", task_id="TASK-001", invocations=[
        {"execution_id": "EXEC-007", "tool_name": "read_file", "arguments": {"path": "a.py"}},
        {"execution_id": "EXEC-008", "tool_name": "read_file", "arguments": {"path": "b.py"}},
    ])
    assert [result.output for result in results] == ["content:a.py", "content:b.py"]
    assert calls == [{"path": "a.py"}, {"path": "b.py"}]
    assert [record.execution_id for record in service.audit.records()] == ["EXEC-007", "EXEC-008"]


def test_invoke_many_rejects_malformed_invocation_before_partial_execution() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    with pytest.raises(ValueError, match="missing required fields"):
        service.invoke_many(role="developer", task_id="TASK-001", invocations=[
            {"execution_id": "EXEC-009", "tool_name": "read_file", "arguments": {"path": "a.py"}},
            {"execution_id": "EXEC-010", "arguments": {"path": "b.py"}},
        ])
    assert calls == [{"path": "a.py"}]


def test_invoke_many_concurrent_preserves_identity_and_audit() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    results = service.invoke_many_concurrent(role="developer", task_id="TASK-001", max_workers=2, invocations=[
        {"execution_id": "BATCH-A", "tool_name": "read_file", "arguments": {"path": "a.py"}},
        {"execution_id": "BATCH-B", "tool_name": "read_file", "arguments": {"path": "b.py"}},
        {"execution_id": "BATCH-C", "tool_name": "read_file", "arguments": {"path": "c.py"}},
    ])
    assert [result.output for result in results] == ["content:a.py", "content:b.py", "content:c.py"]
    records = service.audit.records()
    assert {record.execution_id for record in records} == {"BATCH-A", "BATCH-B", "BATCH-C"}
    assert len(records) == 3
    assert all(record.agent_role == "developer" for record in records)


def test_invoke_many_rejects_duplicate_execution_ids() -> None:
    service = ToolInvocationService(registry=_registry([]))
    with pytest.raises(ValueError, match="duplicate execution_id"):
        service.invoke_many(role="developer", task_id="TASK-001", invocations=[
            {"execution_id": "DUP", "tool_name": "read_file", "arguments": {"path": "a.py"}},
            {"execution_id": "DUP", "tool_name": "read_file", "arguments": {"path": "b.py"}},
        ])
