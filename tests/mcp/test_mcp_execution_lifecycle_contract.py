from __future__ import annotations

import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from mcp_bridge.orchestration import MCPOrchestrationBoundary


def _boundary() -> tuple[MCPOrchestrationBoundary, WorkflowEventLog]:
    manager = TaskManager([
        Task(id="TASK-001", title="First", description="first", role="developer"),
        Task(id="TASK-002", title="Second", description="second", role="developer"),
    ])
    event_log = WorkflowEventLog()

    class Workflow:
        def execute(self, task_id: str, *, execution_id: str):
            task = manager.get_task(task_id)
            task.status = "completed"
            return task

    return (
        MCPOrchestrationBoundary(
            manager,
            workflow_factory=lambda _: Workflow(),
            workflow_event_log=event_log,
            project_id="PROJECT-001",
        ),
        event_log,
    )


def test_execution_ids_are_unique_and_lifecycle_events_are_correlated() -> None:
    boundary, event_log = _boundary()

    first = boundary.execute_task("TASK-001")
    second = boundary.execute_task("TASK-002")

    assert first["execution_id"] != second["execution_id"]
    events = [
        event
        for event in event_log.list_for_project("PROJECT-001")
        if event.payload.get("source") == "mcp"
    ]
    assert len(events) == 4
    for execution_id, task_id in ((first["execution_id"], "TASK-001"), (second["execution_id"], "TASK-002")):
        correlated = [event for event in events if event.payload.get("execution_id") == execution_id]
        assert [event.event_type for event in correlated] == [
            "mcp_task_execution_requested",
            "mcp_task_execution_completed",
        ]
        assert all(event.task_id == task_id for event in correlated)
        assert boundary.execution_status(execution_id)["status"] == "completed"


def test_execution_status_rejects_conflicting_terminal_events() -> None:
    boundary, event_log = _boundary()
    execution_id = "execution-conflict"

    def append(event_type: str, payload: dict) -> None:
        event_log.append(
            WorkflowEvent(
                event_id=f"event-{event_type}",
                event_type=event_type,
                project_id="PROJECT-001",
                task_id="TASK-001",
                occurred_at="2026-09-02T00:00:00Z",
                payload={"execution_id": execution_id, "source": "mcp", **payload},
            )
        )

    append("mcp_task_execution_requested", {})
    append("mcp_task_execution_completed", {"status": "completed"})
    append("mcp_task_execution_failed", {"error_type": "ValueError"})

    with pytest.raises(RuntimeError, match="conflicting terminal events"):
        boundary.execution_status(execution_id)


def test_execution_history_preserves_terminal_outcome_without_exposing_internal_payload() -> None:
    boundary, _ = _boundary()
    result = boundary.execute_task("TASK-001")

    history = boundary.execution_history("TASK-001")
    assert history[-1]["execution_id"] == result["execution_id"]
    assert history[-1]["event_type"] == "mcp_task_execution_completed"
    assert history[-1]["status"] == "completed"
    assert set(history[-1]) == {"event_type", "occurred_at", "execution_id", "status", "error_type"}
