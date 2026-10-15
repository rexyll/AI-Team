from __future__ import annotations

import pytest

from runtime.tool_errors import PERMISSION, classify_tool_exception
from runtime.tool_invocation_service import ToolInvocationService
from tools.terminal import TerminalPolicyError, run_command


def test_terminal_policy_error_keeps_model_facing_message():
    exc = TerminalPolicyError(
        "Executable is not allowed by terminal policy: dir"
    )

    error = classify_tool_exception(exc)

    assert error.category == PERMISSION
    assert error.code == "TOOL_PERMISSION_DENIED"
    assert "terminal policy: dir" in error.message
    assert "Traceback" not in error.message


def test_terminal_policy_error_is_still_a_permission_rejection():
    # Existing security contracts assert a permission-style rejection type.
    with pytest.raises(PermissionError):
        run_command("whoami", ".")


def test_run_command_denial_reports_allowed_executables():
    result = ToolInvocationService().invoke(
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-001",
        tool_name="run_command",
        arguments={"command": "dir /b"},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_PERMISSION_DENIED"
    assert "dir" in result.error.message
    assert "python" in result.error.message


def test_missing_workspace_path_surfaces_actionable_message():
    from tools.filesystem import list_files

    result = ToolInvocationService().invoke(
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-2",
        tool_name="list_files",
        arguments={"path": "does_not_exist_dir"},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_EXECUTION_FAILED"
    assert "not found" in result.error.message.lower() or "not a directory" in result.error.message.lower()


def test_service_tolerates_duplicate_execution_ids_from_resumed_attempts():
    service = ToolInvocationService()
    first = service.invoke(
        role="developer", task_id="TASK-1", execution_id="call_dup",
        tool_name="list_files", arguments={"path": "."},
    )
    second = service.invoke(
        role="developer", task_id="TASK-1", execution_id="call_dup",
        tool_name="list_files", arguments={"path": "."},
    )

    # A resumed attempt may reuse model call ids: the second execution must
    # succeed and stay audited under a disambiguated id, never crash.
    assert first.success is True
    assert second.success is True
    assert "call_dup" in service.history.to_dict()[0]["execution_id"]
    assert any("#2" in item["execution_id"] for item in service.history.to_dict())
