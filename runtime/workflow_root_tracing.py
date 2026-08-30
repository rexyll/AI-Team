from __future__ import annotations

from functools import wraps
from typing import Any

from runtime.tracing import DEFAULT_TRACER


_INSTALL_MARKER = "_ai_team_root_tracing_installed"


def install_workflow_root_tracing() -> None:
    """Install the TaskWorkflow execution root span once.

    The import is intentionally deferred until installation time so the helper
    can be imported without forcing the workflow module to load prematurely.
    """
    from runtime.workflow import TaskWorkflow

    execute = TaskWorkflow.execute
    if getattr(execute, _INSTALL_MARKER, False):
        return

    @wraps(execute)
    def traced_execute(self: Any, task_id: str):
        attributes = {"task_id": task_id}
        project_id = getattr(self, "_project_id", None)
        if isinstance(project_id, str) and project_id.strip():
            attributes["project_id"] = project_id

        with DEFAULT_TRACER.span("workflow.task", attributes=attributes) as span:
            result = execute(self, task_id)
            status = getattr(result, "status", None)
            if isinstance(status, str) and status.strip():
                span.set_attribute("result.status", status)
            return result

    setattr(traced_execute, _INSTALL_MARKER, True)
    TaskWorkflow.execute = traced_execute
