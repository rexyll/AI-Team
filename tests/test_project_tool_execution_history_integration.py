from __future__ import annotations

from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory


def _record_payload(execution_id: str = "TOOL-001") -> dict:
    return {
        "execution_id": execution_id,
        "task_id": "TASK-001",
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


def _manager_with_history() -> TaskManager:
    task = Task(
        id="TASK-001",
        title="developer task",
        description="tool history integration",
        role="developer",
        status="completed",
        result={"status": "completed"},
    )
    task.context["tool_execution_history"] = [_record_payload()]
    return TaskManager([task])


def test_project_persistence_derives_tool_history_from_task_runtime_context(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager_with_history()
    result = ProjectResult.from_task_manager(manager, project="history")

    adapter.save("PROJECT-TOOL-001", plan={"project": "history", "tasks": []}, task_manager=manager, result=result)

    snapshot = adapter.load("PROJECT-TOOL-001")

    assert snapshot.tool_execution_history is not None
    assert snapshot.tool_execution_history.get("TOOL-001").tool_name == "read_file"


def test_project_persistence_explicit_tool_history_overrides_derived_history(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager_with_history()
    history = ToolExecutionHistory.from_dict([_record_payload("TOOL-EXPLICIT")])
    result = ProjectResult.from_task_manager(manager, project="history")

    adapter.save(
        "PROJECT-TOOL-002",
        plan={"project": "history", "tasks": []},
        task_manager=manager,
        result=result,
        tool_execution_history=history,
    )

    snapshot = adapter.load("PROJECT-TOOL-002")

    assert snapshot.tool_execution_history is not None
    assert snapshot.tool_execution_history.list_for_task("TASK-001")[0].execution_id == "TOOL-EXPLICIT"


def test_legacy_project_snapshot_without_tool_history_remains_loadable(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = TaskManager([
        Task(
            id="TASK-001",
            title="legacy",
            description="legacy snapshot",
            role="developer",
            status="completed",
        )
    ])
    result = ProjectResult.from_task_manager(manager, project="legacy")

    adapter.save(
        "PROJECT-TOOL-003",
        plan={"project": "legacy", "tasks": []},
        task_manager=manager,
        result=result,
    )

    path = tmp_path / "PROJECT-TOOL-003.json"
    payload = path.read_text(encoding="utf-8")
    payload = payload.replace(', "tool_execution_history": null', "")
    path.write_text(payload, encoding="utf-8")

    snapshot = adapter.load("PROJECT-TOOL-003")
    assert snapshot.tool_execution_history is None
