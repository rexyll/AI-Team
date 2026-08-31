from __future__ import annotations

import pytest

from runtime.tool_invocation import ToolInvocation


def test_tool_invocation_is_immutable_and_detaches_arguments() -> None:
    arguments = {"path": "src/app.py"}
    request = ToolInvocation(
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-001",
        tool_name="read_file",
        arguments=arguments,
    )
    arguments["path"] = "changed.py"

    assert request.arguments["path"] == "src/app.py"
    assert request.as_dict() == {"path": "src/app.py"}
    with pytest.raises(TypeError):
        request.arguments["path"] = "other.py"  # type: ignore[index]


def test_tool_invocation_rejects_missing_identity_fields() -> None:
    with pytest.raises(ValueError, match="execution_id"):
        ToolInvocation("developer", "TASK-001", "", "read_file", {})


def test_tool_invocation_from_dict_enforces_batch_shape() -> None:
    request = ToolInvocation.from_dict(
        {"execution_id": "EXEC-002", "tool_name": "read_file", "arguments": {"path": "a.py"}},
        role="developer",
        task_id="TASK-001",
    )
    assert request.tool_name == "read_file"
    assert request.execution_id == "EXEC-002"

    with pytest.raises(ValueError, match="missing required fields"):
        ToolInvocation.from_dict({"execution_id": "EXEC-003"}, role="developer", task_id="TASK-001")


def test_tool_invocation_service_accepts_canonical_request() -> None:
    from tests.test_tool_invocation_service import _registry
    from runtime.tool_invocation_service import ToolInvocationService

    calls: list[dict[str, str]] = []
    service = ToolInvocationService(registry=_registry(calls))
    request = ToolInvocation("developer", "TASK-001", "EXEC-004", "read_file", {"path": "src/app.py"})
    result = service.invoke_request(request)

    assert result.success is True
    assert result.output == "content:src/app.py"
    assert calls == [{"path": "src/app.py"}]
