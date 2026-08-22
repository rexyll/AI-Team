from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory


def _record(execution_id: str = "TOOL-001") -> dict:
    return {
        "execution_id": execution_id,
        "task_id": "TASK-001",
        "agent_role": "developer",
        "tool_name": "read_file",
        "started_at": "2026-08-21T00:00:00+00:00",
        "completed_at": "2026-08-21T00:01:00+00:00",
        "status": "completed",
        "arguments": {"path": "src/app.py"},
        "output": {"execution": execution_id},
        "error": None,
        "metadata": {},
    }


def _manager_with_history(execution_id: str = "TOOL-001") -> TaskManager:
    task = Task(
        id="TASK-001",
        title="audit",
        description="cross-boundary audit consistency",
        role="developer",
        status="completed",
        context={"tool_execution_history": [_record(execution_id)]},
    )
    return TaskManager([task])


def _save(adapter: ProjectPersistenceAdapter, project_id: str, manager: TaskManager, history=None) -> None:
    adapter.save(
        project_id,
        plan={"project": "audit", "tasks": []},
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="audit"),
        tool_execution_history=history,
    )


def test_audit_consistency_reports_matching_canonical_and_task_context_history(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager_with_history()
    _save(adapter, "PROJECT-CONSISTENT", manager)

    assert adapter.audit_consistency("PROJECT-CONSISTENT") == {
        "project_id": "PROJECT-CONSISTENT",
        "consistent": True,
        "canonical_count": 1,
        "task_context_count": 1,
        "missing_from_task_context": [],
        "missing_from_canonical": [],
        "conflicting_execution_ids": [],
    }


def test_audit_consistency_reports_explicit_canonical_history_divergence(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager_with_history("TOOL-CONTEXT")
    history = ToolExecutionHistory.from_dict([_record("TOOL-CANONICAL")])
    _save(adapter, "PROJECT-DIVERGENT", manager, history)

    assert adapter.audit_consistency("PROJECT-DIVERGENT") == {
        "project_id": "PROJECT-DIVERGENT",
        "consistent": False,
        "canonical_count": 1,
        "task_context_count": 1,
        "missing_from_task_context": ["TOOL-CANONICAL"],
        "missing_from_canonical": ["TOOL-CONTEXT"],
        "conflicting_execution_ids": [],
    }


def test_audit_consistency_detects_same_execution_id_with_different_payload(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager_with_history()
    canonical = _record()
    canonical["output"] = {"execution": "canonical"}
    _save(
        adapter,
        "PROJECT-CONFLICT",
        manager,
        ToolExecutionHistory.from_dict([canonical]),
    )

    report = adapter.audit_consistency("PROJECT-CONFLICT")

    assert report["consistent"] is False
    assert report["missing_from_task_context"] == []
    assert report["missing_from_canonical"] == []
    assert report["conflicting_execution_ids"] == ["TOOL-001"]


def test_project_orchestrator_exposes_persisted_audit_consistency(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager_with_history()
    _save(adapter, "PROJECT-ORCHESTRATOR", manager)

    project = ProjectOrchestrator(agent_router=object())

    assert project.audit_consistency_persisted("PROJECT-ORCHESTRATOR", adapter)["consistent"] is True
