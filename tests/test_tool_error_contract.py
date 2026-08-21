import pytest

from runtime.tool_errors import (
    ARGUMENT_VALIDATION,
    PERMISSION,
    RUNTIME,
    SANDBOX,
    TIMEOUT,
    ToolError,
    ToolExecutionError,
    ToolTimeoutError,
    classify_tool_exception,
)
from runtime.tool_result import ToolResult
from security.tool_permission import ToolPermissionError


def test_success_result_has_stable_shape():
    result = ToolResult.ok({"value": 42})

    assert result.success is True
    assert result.output == {"value": 42}
    assert result.error is None
    assert result.to_dict() == {
        "success": True,
        "output": {"value": 42},
        "error": None,
    }


def test_failed_result_requires_tool_error():
    error = ToolError("TOOL_RUNTIME", RUNTIME, "execution failed")
    result = ToolResult.fail(error)

    assert result.success is False
    assert result.output is None
    assert result.error == error
    assert result.to_dict()["error"]["code"] == "TOOL_RUNTIME"


def test_result_invariants_are_enforced():
    error = ToolError("X", RUNTIME, "failed")

    with pytest.raises(ValueError):
        ToolResult(success=True, error=error)

    with pytest.raises(ValueError):
        ToolResult(success=False)


def test_permission_error_is_classified_without_leaking_details():
    result = ToolResult.from_exception(
        ToolPermissionError("secret internal permission detail")
    )

    assert result.error is not None
    assert result.error.category == PERMISSION
    assert result.error.code == "TOOL_PERMISSION_DENIED"
    assert "secret internal" not in result.error.message


def test_sandbox_error_is_classified_without_exposing_path():
    exc = PermissionError("Access denied outside workspace: C:/private/secret.txt")
    result = ToolResult.from_exception(exc)

    assert result.error is not None
    assert result.error.category == SANDBOX
    assert result.error.code == "TOOL_SANDBOX_VIOLATION"
    assert "secret.txt" not in result.error.message


def test_argument_validation_error_is_classified():
    exc = type("ToolArgumentValidationError", (ValueError,), {})("bad secret arguments")
    result = ToolResult.from_exception(exc)

    assert result.error is not None
    assert result.error.category == ARGUMENT_VALIDATION
    assert result.error.code == "TOOL_ARGUMENT_INVALID"


def test_timeout_and_runtime_failures_have_distinct_codes():
    timeout = classify_tool_exception(ToolTimeoutError("too slow"))
    runtime = classify_tool_exception(ToolExecutionError("internal runtime detail"))

    assert timeout.category == TIMEOUT
    assert timeout.code == "TOOL_TIMEOUT"
    assert runtime.category == RUNTIME
    assert runtime.code == "TOOL_EXECUTION_FAILED"
    assert runtime.message == "internal runtime detail"


def test_unknown_failure_does_not_expose_exception_details():
    result = ToolResult.from_exception(RuntimeError("api-key=super-secret"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "unknown"
    assert result.error.message == "Tool execution failed"
    assert "super-secret" not in result.to_dict()["error"]["message"]
