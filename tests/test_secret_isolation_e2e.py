from runtime.context_builder import ContextBuilder
from runtime.task import Task
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
from security.secrets import REDACTED


def _record(**overrides):
    payload = {
        "execution_id": "EXEC-SECRET",
        "task_id": "TASK-SECRET",
        "agent_role": "developer",
        "tool_name": "example",
        "started_at": "2026-08-29T00:00:00Z",
        "completed_at": "2026-08-29T00:00:01Z",
        "arguments": {"api_key": "super-secret-api-key", "safe": "visible"},
        "output": {"token": "result-secret", "ok": True},
        "error": "authorization=super-secret-api-key",
        "metadata": {"nested": {"password": "pw-secret"}},
        "status": "failed",
    }
    payload.update(overrides)
    return ToolExecutionRecord(**payload)


def test_secret_cannot_cross_execution_audit_boundary():
    record = _record()

    history = ToolExecutionHistory()
    history.append(record)
    snapshot = ToolExecutionAudit(history).snapshot()
    serialized = str(snapshot)

    assert "super-secret-api-key" not in serialized
    assert "result-secret" not in serialized
    assert "pw-secret" not in serialized
    assert REDACTED in serialized


def test_secret_redaction_is_consistent_between_context_and_execution_record():
    secret = "shared-secret"
    task = Task(
        id="TASK-CONSISTENT",
        title="Secret isolation",
        description="boundary test",
        role="developer",
    )
    task.context = {"token": secret}

    context = ContextBuilder().build_agent_context(task, role="developer")
    record = _record(
        execution_id="EXEC-CONSISTENT",
        task_id=task.id,
        arguments={"token": secret},
        output={"safe": True},
        error=None,
        metadata={"token": secret},
        status="completed",
    )

    assert context.metadata["token"] == REDACTED
    assert record.arguments["token"] == REDACTED
    assert record.metadata["token"] == REDACTED
    assert task.context["token"] == secret
