from runtime.tool_execution_record import ToolExecutionRecord
from security.secrets import REDACTED


def _record(**overrides):
    payload = {
        "execution_id": "exec-secret-001",
        "task_id": "TASK-SECRET",
        "agent_role": "developer",
        "tool_name": "test_tool",
        "started_at": "2026-08-29T00:00:00Z",
        "completed_at": "2026-08-29T00:00:01Z",
        "status": "completed",
        "arguments": {"api_key": "super-secret", "value": "safe"},
        "output": {"token": "output-secret", "value": "ok"},
        "error": None,
        "metadata": {"authorization": "Bearer secret"},
    }
    payload.update(overrides)
    return ToolExecutionRecord(**payload)


def test_tool_execution_record_redacts_arguments_output_and_metadata():
    record = _record()

    assert record.arguments["api_key"] == REDACTED
    assert record.arguments["value"] == "safe"
    assert record.output["token"] == REDACTED
    assert record.output["value"] == "ok"
    assert record.metadata["authorization"] == REDACTED


def test_tool_execution_record_redacts_error_details():
    record = _record(
        status="failed",
        completed_at="2026-08-29T00:00:01Z",
        error={"message": "request failed token=error-secret", "token": "error-secret"},
    )

    assert record.error["token"] == REDACTED
    assert REDACTED in record.error["message"]
    assert "error-secret" not in record.error["message"]


def test_tool_execution_record_does_not_mutate_inputs():
    arguments = {"password": "original-secret"}
    output = {"safe": "value"}
    record = _record(arguments=arguments, output=output)

    assert arguments["password"] == "original-secret"
    assert record.arguments["password"] == REDACTED
    assert output == {"safe": "value"}
