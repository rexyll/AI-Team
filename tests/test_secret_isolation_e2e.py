from runtime.tool_execution_record import ToolExecutionRecord
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.context_builder import ContextBuilder
from runtime.task import Task
from security.secrets import REDACTED, redact_value


def test_secret_cannot_cross_execution_audit_boundary():
    secret = "super-secret-api-key"
    record = ToolExecutionRecord(
        execution_id="EXEC-SECRET",
        task_id="TASK-SECRET",
        agent_role="developer",
        tool_name="example",
        arguments={"api_key": secret, "safe": "visible"},
        output={"token": "result-secret", "ok": True},
        error=f"authorization={secret}",
        metadata={"nested": {"password": "pw-secret"}},
        status="failed",
    )

    history = ToolExecutionHistory()
    history.append(record)
    snapshot = ToolExecutionAudit(history).snapshot()
    serialized = str(snapshot)

    assert secret not in serialized
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
    record = ToolExecutionRecord(
        execution_id="EXEC-CONSISTENT",
        task_id=task.id,
        agent_role="developer",
        tool_name="example",
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
