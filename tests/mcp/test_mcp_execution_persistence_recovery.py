from __future__ import annotations

from datetime import datetime, timezone

from mcp_bridge.orchestration import MCPOrchestrationBoundary
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter


def _event(event_id: str, event_type: str, *, task_id: str = "TASK-RECOVERED", payload=None) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id="PROJECT-RECOVERY",
        task_id=task_id,
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        payload=payload or {},
    )


def test_mcp_execution_identity_and_idempotency_survive_event_log_recovery(tmp_path) -> None:
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    original = WorkflowEventLog(persistence_sink=adapter)
    execution_id = "exec-recovered-001"

    original.append(
        _event(
            "event-request",
            "mcp_task_execution_requested",
            payload={"source": "mcp", "execution_id": execution_id, "idempotency_key": "idem-recovered"},
        )
    )
    original.append(
        _event(
            "event-complete",
            "mcp_task_execution_completed",
            payload={"source": "mcp", "execution_id": execution_id, "status": "completed"},
        )
    )

    recovered_log = adapter.load_log()
    manager = TaskManager([Task(id="TASK-RECOVERED", title="Recovered", description="done", role="developer", status="completed")])
    calls: list[str] = []

    class Workflow:
        def execute(self, task_id: str, *, execution_id: str):
            calls.append(execution_id)
            raise AssertionError("recovered idempotent execution must not execute again")

    boundary = MCPOrchestrationBoundary(
        manager,
        workflow_factory=lambda _task_id: Workflow(),
        workflow_event_log=recovered_log,
        project_id="PROJECT-RECOVERY",
    )

    result = boundary.execute_task("TASK-RECOVERED", idempotency_key="idem-recovered")

    assert result["execution_id"] == execution_id
    assert result["status"] == "completed"
    assert calls == []
    status = boundary.execution_status(execution_id)
    assert status["status"] == "completed"
    assert status["task_id"] == "TASK-RECOVERED"
    history = boundary.execution_history("TASK-RECOVERED")
    assert [item["execution_id"] for item in history] == [execution_id, execution_id]
