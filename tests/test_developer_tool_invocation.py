from __future__ import annotations

from typing import Any

from runtime.developer_tool_invocation import DeveloperToolInvocationAdapter
from runtime.tool_invocation_service import ToolInvocationService
from tools.registry import ToolRegistry


def _registry(calls: list[dict[str, Any]]) -> ToolRegistry:
    registry = ToolRegistry()

    def read_file(path: str) -> str:
        calls.append({"path": path})
        return f"content:{path}"

    registry.register(
        "read_file",
        read_file,
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


def test_developer_adapter_forces_developer_role() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    adapter = DeveloperToolInvocationAdapter(service)

    result = adapter.invoke(
        task_id="TASK-001",
        execution_id="EXEC-DEV-001",
        tool_name="read_file",
        arguments={"path": "src/app.py"},
    )

    assert result.success is True
    assert result.output == "content:src/app.py"
    record = service.audit.records()[0]
    assert record.agent_role == "developer"
    assert record.task_id == "TASK-001"
    assert record.execution_id == "EXEC-DEV-001"
    assert calls == [{"path": "src/app.py"}]


def test_developer_adapter_batch_preserves_execution_identity() -> None:
    calls: list[dict[str, Any]] = []
    service = ToolInvocationService(registry=_registry(calls))
    adapter = DeveloperToolInvocationAdapter(service)

    results = adapter.invoke_many(
        task_id="TASK-001",
        invocations=[
            {"execution_id": "EXEC-DEV-002", "tool_name": "read_file", "arguments": {"path": "a.py"}},
            {"execution_id": "EXEC-DEV-003", "tool_name": "read_file", "arguments": {"path": "b.py"}},
        ],
    )

    assert [result.output for result in results] == ["content:a.py", "content:b.py"]
    assert [record.execution_id for record in service.audit.records()] == [
        "EXEC-DEV-002",
        "EXEC-DEV-003",
    ]
    assert all(record.agent_role == "developer" for record in service.audit.records())
