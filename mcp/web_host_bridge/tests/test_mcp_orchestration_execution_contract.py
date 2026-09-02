from __future__ import annotations

import pytest

from web_host_bridge.orchestration import MCPOrchestrationBoundary
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog


def test_workflow_type_error_body_is_not_masked_by_compatibility_fallback() -> None:
    manager = TaskManager([
        Task(id="TASK-001", title="First", description="first", role="developer"),
    ])
    event_log = WorkflowEventLog()

    class Workflow:
        def execute(self, task_id: str, *, execution_id: str):
            raise TypeError("workflow body failed while processing execution_id")

    boundary = MCPOrchestrationBoundary(
        manager,
        workflow_factory=lambda _: Workflow(),
        workflow_event_log=event_log,
        project_id="PROJECT-001",
    )

    with pytest.raises(TypeError, match="workflow body failed"):
        boundary.execute_task("TASK-001", idempotency_key="request-001")

    history = boundary.execution_history("TASK-001")
    assert [item["event_type"] for item in history] == [
        "mcp_task_execution_requested",
        "mcp_task_execution_failed",
    ]
    assert history[-1]["error_type"] == "TypeError"


def test_legacy_workflow_without_execution_id_remains_supported() -> None:
    manager = TaskManager([
        Task(id="TASK-001", title="First", description="first", role="developer"),
    ])

    class LegacyWorkflow:
        def execute(self, task_id: str):
            task = manager.get_task(task_id)
            task.status = "completed"
            return task

    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: LegacyWorkflow())
    result = boundary.execute_task("TASK-001")

    assert result["status"] == "completed"
    assert result["execution_id"]
