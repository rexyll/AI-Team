from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
from core.project_orchestrator import ProjectOrchestrator


def _record(execution_id: str, task_id: str) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id=execution_id,
        task_id=task_id,
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-21T10:00:00Z",
        completed_at="2026-08-21T10:00:01Z",
        status="completed",
        arguments={"path": "README.md"},
        output="ok",
    )


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id="TASK-001",
                title="one",
                description="one",
                role="developer",
                status="completed",
                context={"tool_execution_history": [_record("STALE-001", "TASK-001").to_dict()]},
            ),
            Task(
                id="TASK-002",
                title="two",
                description="two",
                role="developer",
                status="completed",
                context={"tool_execution_history": [_record("STALE-002", "TASK-002").to_dict()]},
            ),
        ]
    )


def test_persisted_explicit_history_replaces_stale_task_context_history(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    history = ToolExecutionHistory()
    history.append(_record("CANONICAL-001", "TASK-001"))

    adapter.save(
        "PROJECT-HISTORY-001",
        plan={"project": "history", "tasks": []},
        task_manager=manager,
        tool_execution_history=history,
    )

    restored = ProjectOrchestrator(agent_router=object())
    restored.resume_persisted("PROJECT-HISTORY-001", adapter)

    tasks = {task.id: task for task in restored.last_task_manager.get_all_tasks()}
    assert tasks["TASK-001"].context["tool_execution_history"] == [
        _record("CANONICAL-001", "TASK-001").to_dict()
    ]
    assert "tool_execution_history" not in tasks["TASK-002"].context


def test_rehydrated_task_context_is_consistent_with_persisted_audit(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    history = ToolExecutionHistory()
    history.append(_record("CANONICAL-001", "TASK-001"))

    adapter.save(
        "PROJECT-HISTORY-002",
        plan={"project": "history", "tasks": []},
        task_manager=manager,
        tool_execution_history=history,
    )

    restored = ProjectOrchestrator(agent_router=object())
    restored.resume_persisted("PROJECT-HISTORY-002", adapter)
    audit = restored.audit_persisted("PROJECT-HISTORY-002", adapter)

    task_records = restored.last_task_manager.get_task("TASK-001").context[
        "tool_execution_history"
    ]
    assert task_records == audit.history.to_dict()
