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


def _record(task_id: str) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id="EXEC-001",
        task_id=task_id,
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-21T00:00:00Z",
        completed_at="2026-08-21T00:00:01Z",
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
