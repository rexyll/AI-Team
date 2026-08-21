import json

import pytest

from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id="TASK-001",
                title="implementation",
                description="build feature",
                role="developer",
                status="pending",
            )
        ]
    )


def _record(task_id: str, execution_id: str = "EXEC-001") -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id=execution_id,
        task_id=task_id,
        agent_role="developer",
        tool_name="read_file",
        started_at=f"2026-08-21T00:00:0{execution_id[-1]}Z",
        completed_at=f"2026-08-21T00:00:1{execution_id[-1]}Z",
        status="completed",
        arguments={"path": "README.md"},
        output="ok",
    )


def test_project_save_rejects_tool_log_for_unknown_task(tmp_path):
    history = ToolExecutionHistory()
    history.append(_record("TASK-UNKNOWN"))

    with pytest.raises(ValueError, match="unknown task"):
        ProjectPersistenceAdapter(tmp_path).save(
            "PROJECT-001",
            plan=None,
            task_manager=_manager(),
            tool_execution_history=history,
        )


def test_project_load_rejects_tool_log_for_unknown_task(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save(
        "PROJECT-001",
        plan=None,
        task_manager=_manager(),
    )

    path = tmp_path / "PROJECT-001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tool_execution_history"] = [_record("TASK-UNKNOWN").to_dict()]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown task"):
        adapter.load("PROJECT-001")


def test_project_snapshot_round_trips_tool_logs_for_known_tasks(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    history = ToolExecutionHistory()
    history.append(_record("TASK-001"))

    adapter.save(
        "PROJECT-001",
        plan=None,
        task_manager=_manager(),
        tool_execution_history=history,
    )

    snapshot = adapter.load("PROJECT-001")

    assert snapshot.tool_execution_history is not None
    assert snapshot.tool_execution_history.get("EXEC-001").task_id == "TASK-001"


def test_explicit_project_history_overrides_task_context_history(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    derived = _record("TASK-001", execution_id="EXEC-001")
    explicit = _record("TASK-001", execution_id="EXEC-002")
    manager.get_task("TASK-001").context["tool_execution_history"] = [derived.to_dict()]

    history = ToolExecutionHistory()
    history.append(explicit)
    adapter.save(
        "PROJECT-001",
        plan=None,
        task_manager=manager,
        tool_execution_history=history,
    )

    snapshot = adapter.load("PROJECT-001")

    assert snapshot.tool_execution_history is not None
    assert snapshot.tool_execution_history.get("EXEC-002") == explicit
    with pytest.raises(KeyError):
        snapshot.tool_execution_history.get("EXEC-001")


def test_repeated_project_checkpoint_does_not_duplicate_tool_logs(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    record = _record("TASK-001")
    manager.get_task("TASK-001").context["tool_execution_history"] = [record.to_dict()]

    adapter.save("PROJECT-001", plan=None, task_manager=manager)
    adapter.update("PROJECT-001", plan=None, task_manager=manager)
    adapter.update("PROJECT-001", plan=None, task_manager=manager)

    snapshot = adapter.load("PROJECT-001")

    assert snapshot.tool_execution_history is not None
    assert len(snapshot.tool_execution_history) == 1
    assert snapshot.tool_execution_history.get("EXEC-001") == record


def test_project_checkpoint_appends_new_tool_logs_without_losing_old_logs(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    first = _record("TASK-001", execution_id="EXEC-001")
    second = _record("TASK-001", execution_id="EXEC-002")

    manager.get_task("TASK-001").context["tool_execution_history"] = [first.to_dict()]
    adapter.save("PROJECT-001", plan=None, task_manager=manager)

    manager.get_task("TASK-001").context["tool_execution_history"] = [
        first.to_dict(),
        second.to_dict(),
    ]
    adapter.update("PROJECT-001", plan=None, task_manager=manager)

    snapshot = adapter.load("PROJECT-001")

    assert snapshot.tool_execution_history is not None
    assert len(snapshot.tool_execution_history) == 2
    assert snapshot.tool_execution_history.get("EXEC-001") == first
    assert snapshot.tool_execution_history.get("EXEC-002") == second
