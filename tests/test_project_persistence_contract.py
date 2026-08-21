import json

import pytest

from core.project_result import ProjectResult
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.project_persistence import ProjectPersistenceAdapter


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id="PROJECT-TASK-001",
                title="design",
                description="design the project",
                role="architect",
                status="completed",
                result={"status": "completed"},
            ),
            Task(
                id="PROJECT-TASK-002",
                title="implementation",
                description="implement the project",
                role="developer",
                status="ready",
                dependencies=["PROJECT-TASK-001"],
            ),
        ]
    )


def _plan() -> dict:
    return {
        "project": "persistence-demo",
        "summary": "project persistence contract",
        "tasks": [
            {
                "id": "PROJECT-TASK-001",
                "title": "design",
                "description": "design the project",
                "role": "architect",
                "dependencies": [],
            },
            {
                "id": "PROJECT-TASK-002",
                "title": "implementation",
                "description": "implement the project",
                "role": "developer",
                "dependencies": ["PROJECT-TASK-001"],
            },
        ],
    }


def _result() -> ProjectResult:
    return ProjectResult(
        project="persistence-demo",
        success=False,
        status="incomplete",
        total_tasks=2,
        completed_tasks=1,
        failed_tasks=(),
        blocked_tasks=(),
    )


def test_project_persistence_round_trip_preserves_plan_tasks_and_result(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    plan = _plan()
    result = _result()

    adapter.save("PROJECT-001", plan=plan, task_manager=manager, result=result)
    snapshot = adapter.load("PROJECT-001")

    assert snapshot.project_id == "PROJECT-001"
    assert snapshot.plan == plan
    assert [task.to_dict() for task in snapshot.task_manager.get_all_tasks()] == [
        task.to_dict() for task in manager.get_all_tasks()
    ]
    assert snapshot.result.to_dict() == result.to_dict()


def test_project_persistence_is_json_serializable(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("PROJECT-001", plan=_plan(), task_manager=_manager(), result=_result())

    payload = json.loads(
        (tmp_path / "PROJECT-001.json").read_text(encoding="utf-8")
    )

    assert payload["project_id"] == "PROJECT-001"
    assert isinstance(payload["plan"], dict)
    assert isinstance(payload["tasks"], list)
    assert isinstance(payload["result"], dict)


def test_project_persistence_requires_explicit_identity(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)

    with pytest.raises(ValueError):
        adapter.save("", plan=_plan(), task_manager=_manager(), result=_result())


def test_project_persistence_rejects_duplicate_identity(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("PROJECT-001", plan=_plan(), task_manager=_manager(), result=_result())

    with pytest.raises(FileExistsError):
        adapter.save("PROJECT-001", plan=_plan(), task_manager=_manager(), result=_result())


def test_project_persistence_missing_project_is_explicit(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)

    with pytest.raises(KeyError):
        adapter.load("MISSING-PROJECT")


def test_project_persistence_rejects_corrupt_payload(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    (tmp_path / "PROJECT-001.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError):
        adapter.load("PROJECT-001")


def test_project_persistence_delete_is_explicit(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("PROJECT-001", plan=_plan(), task_manager=_manager(), result=_result())

    adapter.delete("PROJECT-001")

    with pytest.raises(KeyError):
        adapter.load("PROJECT-001")


def test_project_persistence_list_ids_is_stable(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("PROJECT-002", plan=_plan(), task_manager=_manager(), result=_result())
    adapter.save("PROJECT-001", plan=_plan(), task_manager=_manager(), result=_result())

    assert adapter.list_ids() == ["PROJECT-001", "PROJECT-002"]
