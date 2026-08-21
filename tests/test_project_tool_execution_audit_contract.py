from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
from runtime.task import Task
from runtime.task_manager import TaskManager


def _record(execution_id: str, task_id: str = "TASK-001", role: str = "developer") -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id=execution_id,
        task_id=task_id,
        agent_role=role,
        tool_name="read_file",
        started_at="2026-08-21T00:00:00+00:00",
        completed_at="2026-08-21T00:01:00+00:00",
        status="completed",
        arguments={"path": "src/app.py"},
        output={"execution": execution_id},
        error=None,
        metadata={},
    )


def _save_project(tmp_path):
    task = Task(
        id="TASK-001",
        title="audit",
        description="audit persisted tool history",
        role="developer",
        status="completed",
        context={"tool_execution_history": [_record("TOOL-001").to_dict()]},
    )
    manager = TaskManager([task])
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save(
        "PROJECT-AUDIT-001",
        plan={"project": "audit", "tasks": [{"id": "TASK-001"}]},
        task_manager=manager,
        result=None,
    )
    return adapter


def test_project_persistence_exposes_audit_over_restored_history(tmp_path):
    adapter = _save_project(tmp_path)

    audit = adapter.audit("PROJECT-AUDIT-001")

    assert isinstance(audit, ToolExecutionAudit)
    assert [record.execution_id for record in audit.records()] == ["TOOL-001"]
    assert audit.count(task_id="TASK-001") == 1


def test_project_audit_is_consistent_with_snapshot_after_reload(tmp_path):
    adapter = _save_project(tmp_path)
    snapshot = adapter.load("PROJECT-AUDIT-001")
    audit = adapter.audit("PROJECT-AUDIT-001")

    assert audit.history.to_dict() == snapshot.tool_execution_history.to_dict()


def test_project_orchestrator_audit_persisted_delegates_to_persistence_boundary(tmp_path):
    adapter = _save_project(tmp_path)
    orchestrator = ProjectOrchestrator(agent_router=object())

    audit = orchestrator.audit_persisted("PROJECT-AUDIT-001", adapter)

    assert audit.summary() == {
        "total": 1,
        "by_status": {"completed": 1},
        "by_tool": {"read_file": 1},
        "by_agent_role": {"developer": 1},
    }
