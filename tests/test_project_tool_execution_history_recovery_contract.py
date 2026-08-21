from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory


def _record_payload(execution_id: str, task_id: str = "TASK-001") -> dict:
    return {
        "execution_id": execution_id,
        "task_id": task_id,
        "agent_role": "developer",
        "tool_name": "read_file",
        "started_at": "2026-08-21T00:00:00+00:00",
        "completed_at": "2026-08-21T00:00:01+00:00",
        "status": "completed",
        "arguments": {"path": "src/app.py"},
        "output": {"bytes": 42},
        "error": None,
        "metadata": {},
    }


def _manager() -> TaskManager:
    task = Task(
        id="TASK-001",
        title="developer task",
        description="tool history recovery",
        role="developer",
        status="completed",
        result={"status": "completed"},
    )
    task.context["tool_execution_history"] = [_record_payload("TOOL-TASK-CONTEXT")]
    return TaskManager([task])


def _plan() -> dict:
    return {
        "project": "history-recovery",
        "summary": "recover canonical tool history",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "developer task",
                "description": "tool history recovery",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def test_resume_persisted_rehydrates_canonical_project_history_into_task_context(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    result = ProjectResult.from_task_manager(manager, project="history-recovery")
    explicit_history = ToolExecutionHistory.from_dict(
        [_record_payload("TOOL-PROJECT-CANONICAL")]
    )

    adapter.save(
        "PROJECT-HISTORY-RECOVERY-001",
        plan=_plan(),
        task_manager=manager,
        result=result,
        tool_execution_history=explicit_history,
    )

    project = ProjectOrchestrator(agent_router=object())
    restored = project.resume_persisted("PROJECT-HISTORY-RECOVERY-001", adapter)

    assert restored == result
    task = project.last_task_manager.get_task("TASK-001")
    assert task.context["tool_execution_history"] == [
        _record_payload("TOOL-PROJECT-CANONICAL")
    ]


def test_resume_persisted_does_not_retain_stale_task_history_when_project_history_is_canonical(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    result = ProjectResult.from_task_manager(manager, project="history-recovery")
    explicit_history = ToolExecutionHistory.from_dict(
        [_record_payload("TOOL-PROJECT-CANONICAL")]
    )

    adapter.save(
        "PROJECT-HISTORY-RECOVERY-002",
        plan=_plan(),
        task_manager=manager,
        result=result,
        tool_execution_history=explicit_history,
    )

    project = ProjectOrchestrator(agent_router=object())
    project.resume_persisted("PROJECT-HISTORY-RECOVERY-002", adapter)

    task = project.last_task_manager.get_task("TASK-001")
    execution_ids = [
        item["execution_id"] for item in task.context["tool_execution_history"]
    ]
    assert execution_ids == ["TOOL-PROJECT-CANONICAL"]
