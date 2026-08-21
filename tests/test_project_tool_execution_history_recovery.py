from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord


def _record(execution_id: str, task_id: str = "TASK-001") -> dict:
    return {
        "execution_id": execution_id,
        "task_id": task_id,
        "agent_role": "developer",
        "tool_name": "read_file",
        "started_at": f"2026-08-21T00:00:{execution_id[-2:]}+00:00",
        "completed_at": f"2026-08-21T00:01:{execution_id[-2:]}+00:00",
        "status": "completed",
        "arguments": {"path": "src/app.py"},
        "output": {"execution": execution_id},
        "error": None,
        "metadata": {},
    }


def _manager() -> TaskManager:
    task = Task(
        id="TASK-001",
        title="continue developer task",
        description="append tool history after recovery",
        role="developer",
        status="ready",
    )
    task.context["tool_execution_history"] = [_record("TOOL-001")]
    return TaskManager([task])


class HistoryContinuingOrchestrator:
    """Execution seam that simulates a resumed Developer producing one new record."""

    def __init__(self, task_manager: TaskManager, agent_router: object):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.state_change_hook = None

    def set_state_change_hook(self, hook):
        self.state_change_hook = hook

    def run(self):
        task = self.task_manager.get_all_tasks()[0]
        history = ToolExecutionHistory.from_dict(
            task.context.get("tool_execution_history", [])
        )
        history.append(
            ToolExecutionRecord.from_dict(_record("TOOL-002"))
        )
        task.context["tool_execution_history"] = history.to_dict()
        self.task_manager.mark_running(task.id)
        if self.state_change_hook is not None:
            self.state_change_hook(self.task_manager)
        self.task_manager.mark_completed(task.id, {"status": "completed"})
        if self.state_change_hook is not None:
            self.state_change_hook(self.task_manager)


def _factory(task_manager: TaskManager, agent_router: object):
    return HistoryContinuingOrchestrator(task_manager, agent_router)


def test_continue_persisted_restores_old_history_and_appends_new_record(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    result = ProjectResult.from_task_manager(manager, project="history-recovery")
    adapter.save(
        "PROJECT-HISTORY-RECOVERY-001",
        plan={"project": "history-recovery", "tasks": []},
        task_manager=manager,
        result=result,
        tool_execution_history=ToolExecutionHistory.from_dict(
            [_record("TOOL-001")]
        ),
    )

    project = ProjectOrchestrator(
        agent_router=object(),
        orchestrator_factory=_factory,
    )
    result = project.continue_persisted("PROJECT-HISTORY-RECOVERY-001", adapter)

    assert result.success is True
    restored = adapter.load("PROJECT-HISTORY-RECOVERY-001")
    assert restored.tool_execution_history is not None
    records = restored.tool_execution_history.list_for_task("TASK-001")
    assert [record.execution_id for record in records] == ["TOOL-001", "TOOL-002"]
    assert restored.task_manager.get_task("TASK-001").context["tool_execution_history"] == [
        _record("TOOL-001"),
        _record("TOOL-002"),
    ]


def test_continue_persisted_does_not_duplicate_existing_tool_execution_records(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    adapter.save(
        "PROJECT-HISTORY-RECOVERY-002",
        plan={"project": "history-recovery", "tasks": []},
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="history-recovery"),
    )

    project = ProjectOrchestrator(
        agent_router=object(),
        orchestrator_factory=_factory,
    )
    project.continue_persisted("PROJECT-HISTORY-RECOVERY-002", adapter)

    restored = adapter.load("PROJECT-HISTORY-RECOVERY-002")
    assert restored.tool_execution_history is not None
    assert len(restored.tool_execution_history) == 2
    assert [record.execution_id for record in restored.tool_execution_history.list_for_task("TASK-001")] == [
        "TOOL-001",
        "TOOL-002",
    ]
