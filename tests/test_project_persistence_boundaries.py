import json

import pytest

from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def _manager() -> TaskManager:
    return TaskManager([
        Task(
            id="BOUNDARY-TASK-001",
            title="design",
            description="design",
            role="architect",
            status="completed",
            status_history=[{"from": "ready", "to": "completed"}],
            retry_attempt=1,
            max_retries=2,
            result={"status": "completed"},
        )
    ])


def _plan() -> dict:
    return {"project": "boundary-demo", "summary": "boundary", "tasks": []}


def _result() -> ProjectResult:
    return ProjectResult(
        project="boundary-demo",
        success=True,
        status="completed",
        total_tasks=1,
        completed_tasks=1,
        failed_tasks=(),
        blocked_tasks=(),
    )


def test_project_snapshot_restores_independent_runtime_objects(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    adapter.save("BOUNDARY-001", plan=_plan(), task_manager=manager, result=_result())

    snapshot = adapter.load("BOUNDARY-001")

    assert snapshot.task_manager is not manager
    assert snapshot.task_manager.get_all_tasks()[0] is not manager.get_all_tasks()[0]


def test_project_persistence_rejects_identity_mismatch(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("BOUNDARY-001", plan=_plan(), task_manager=_manager(), result=_result())

    path = tmp_path / "BOUNDARY-001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["project_id"] = "OTHER-PROJECT"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        adapter.load("BOUNDARY-001")


def test_project_persistence_rejects_invalid_plan_schema(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("BOUNDARY-001", plan=_plan(), task_manager=_manager(), result=_result())

    path = tmp_path / "BOUNDARY-001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["plan"] = ["invalid"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        adapter.load("BOUNDARY-001")


def test_project_persistence_rejects_invalid_task_schema(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("BOUNDARY-001", plan=_plan(), task_manager=_manager(), result=_result())

    path = tmp_path / "BOUNDARY-001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"][0].pop("id")
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        adapter.load("BOUNDARY-001")


def test_project_persistence_rejects_invalid_result_schema(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("BOUNDARY-001", plan=_plan(), task_manager=_manager(), result=_result())

    path = tmp_path / "BOUNDARY-001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["result"]["success"] = "yes"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        adapter.load("BOUNDARY-001")


def test_project_persistence_rejects_path_traversal_identity(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)

    for project_id in ("../escape", "nested/project", ".", ".."):
        with pytest.raises(ValueError):
            adapter.save(project_id, plan=_plan(), task_manager=_manager(), result=_result())


def test_project_persistence_list_ids_ignores_non_json_entries(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("BOUNDARY-002", plan=_plan(), task_manager=_manager(), result=_result())
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "ignored.json").mkdir()

    assert adapter.list_ids() == ["BOUNDARY-002"]


def test_project_persistence_delete_does_not_remove_unrelated_files(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("BOUNDARY-001", plan=_plan(), task_manager=_manager(), result=_result())
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    adapter.delete("BOUNDARY-001")

    assert unrelated.read_text(encoding="utf-8") == "keep"
