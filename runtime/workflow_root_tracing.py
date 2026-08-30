from __future__ import annotations

from functools import wraps
from typing import Any

from runtime.tracing import DEFAULT_TRACER


_INSTALL_MARKER = "_ai_team_root_tracing_installed"
_LEASE_MARKER = "_ai_team_execution_lease_installed"


def install_workflow_root_tracing() -> None:
    """Install workflow observability and opt-in execution leasing once."""
    from runtime.workflow import TaskWorkflow

    execute = TaskWorkflow.execute
    if not getattr(execute, _INSTALL_MARKER, False):
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

    _install_execution_lease_boundary(TaskWorkflow)


def _install_execution_lease_boundary(TaskWorkflow) -> None:
    """Make TaskWorkflow lease-aware without changing legacy constructor semantics.

    A workflow opts in by setting ``_execution_lease`` to a
    ``WorkflowExecutionLease`` instance. The lease covers the complete
    canonical execute call, including all Developer/Tester/Reviewer rounds.
    """
    execute = TaskWorkflow.execute
    if getattr(execute, _LEASE_MARKER, False):
        return

    @wraps(execute)
    def leased_execute(self: Any, task_id: str):
        lease = getattr(self, "_execution_lease", None)
        if lease is None:
            return execute(self, task_id)
        return lease.run(task_id, lambda _execution_lease: execute(self, task_id))

    setattr(leased_execute, _LEASE_MARKER, True)
    TaskWorkflow.execute = leased_execute


def attach_execution_lease(workflow: Any, execution_lease: Any) -> Any:
    """Opt a TaskWorkflow instance into the canonical execution lease boundary."""
    if workflow is None:
        raise ValueError("workflow is required")
    if execution_lease is None or not callable(getattr(execution_lease, "run", None)):
        raise TypeError("execution_lease must provide a callable run method")
    setattr(workflow, "_execution_lease", execution_lease)
    return workflow


__all__ = ["attach_execution_lease", "install_workflow_root_tracing"]
