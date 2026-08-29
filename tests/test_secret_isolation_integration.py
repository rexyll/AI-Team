from runtime.context_builder import ContextBuilder
from runtime.task import Task
from security.secrets import REDACTED


def test_agent_context_redacts_secret_metadata():
    task = Task(
        id="TASK-SECRET",
        title="Secret isolation",
        description="Verify secret boundaries",
        role="developer",
    )
    task.context = {
        "api_key": "super-secret",
        "safe": "visible",
        "nested": {"Authorization": "Bearer abc123"},
    }

    context = ContextBuilder().build_agent_context(task, role="developer")

    assert context.metadata["api_key"] == REDACTED
    assert context.metadata["nested"]["Authorization"] == REDACTED
    assert context.metadata["safe"] == "visible"


def test_agent_context_redaction_does_not_mutate_task_context():
    task = Task(
        id="TASK-SECRET-2",
        title="Secret isolation",
        description="Verify detached sanitization",
        role="developer",
    )
    task.context = {"token": "original-secret"}

    context = ContextBuilder().build_agent_context(task, role="developer")

    assert context.metadata["token"] == REDACTED
    assert task.context["token"] == "original-secret"
