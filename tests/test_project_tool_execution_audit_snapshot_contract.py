from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord


def _record(execution_id: str, *, task_id: str = "TASK-001") -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id=execution_id,
        task_id=task_id,
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-21T00:00:00+00:00",
        completed_at="2026-08-21T00:01:00+00:00",
        status="completed",
        arguments={"path": "src/app.py"},
        output={"execution": execution_id},
        error=None,
        metadata={},
    )


def _manager() -> TaskManager:
    return TaskManager([
        Task(
            id="TASK-001",
            title="audit",
            description="audit",
            role="developer",
            status="ready",
        )
    ])


def _plan() -> dict:
    return {
        "project": "Audit Project",
        "summary": "audit",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "audit",
                "description": "audit",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def _history() -> ToolExecutionHistory:
    return ToolExecutionHistory.from_dict([_record("TOOL-001").to_dict()])


def test_project_persistence_exposes_detached_audit_snapshot(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    adapter.save(
        "PROJECT-AUDIT-001",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Audit Project"),
        tool_execution_history=_history(),
    )

    snapshot = adapter.audit_snapshot("PROJECT-AUDIT-001")

    assert snapshot == {
        "records": [_record("TOOL-001").to_dict()],
        "summary": {
            "total": 1,
            "by_status": {"completed": 1},
            "by_tool": {"read_file": 1},
            "by_agent_role": {"developer": 1},
        },
    }

    snapshot["records"][0]["arguments"]["path"] = "mutated"
    assert adapter.audit_snapshot("PROJECT-AUDIT-001")["records"][0]["arguments"]["path"] == "src/app.py"


def test_project_orchestrator_exposes_persisted_audit_snapshot(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    adapter.save(
        "PROJECT-AUDIT-002",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Audit Project"),
        tool_execution_history=_history(),
    )

    project = ProjectOrchestrator(agent_router=object())
    audit = project.audit_persisted("PROJECT-AUDIT-002", adapter)
    snapshot = project.audit_snapshot_persisted("PROJECT-AUDIT-002", adapter)

    assert audit.summary()["total"] == 1
    assert [record.execution_id for record in audit.records(task_id="TASK-001")] == ["TOOL-001"]
    assert snapshot["records"] == [_record("TOOL-001").to_dict()]
    assert snapshot["summary"]["total"] == 1
