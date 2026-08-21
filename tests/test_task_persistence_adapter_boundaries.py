import json

import pytest

from runtime.task import Task
from runtime.task_persistence import TaskPersistenceAdapter


def _task(task_id: str = "BOUNDARY-001") -> Task:
    return Task(
        id=task_id,
        title="Boundary",
        description="adapter boundary",
        role="developer",
    )


def test_adapter_rejects_path_traversal_task_ids(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)

    for task_id in ("../escape", "nested/task", "", ".", ".."):
        with pytest.raises(ValueError):
            adapter.load(task_id)


def test_adapter_rejects_non_string_task_ids(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)

    with pytest.raises(ValueError):
        adapter.load(123)  # type: ignore[arg-type]


def test_adapter_rejects_valid_json_with_invalid_task_payload(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    (tmp_path / "BOUNDARY-001.json").write_text(
        json.dumps({"id": "BOUNDARY-001"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        adapter.load("BOUNDARY-001")


def test_adapter_save_failure_does_not_leave_temporary_file(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    task = _task()
    task.context = {"not_json": object()}

    with pytest.raises(ValueError):
        adapter.save(task)

    assert not (tmp_path / ".BOUNDARY-001.json.tmp").exists()
    assert not (tmp_path / "BOUNDARY-001.json").exists()


def test_adapter_list_ids_ignores_non_json_and_directories(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    adapter.save(_task())
    (tmp_path / "README.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "subdir.json").mkdir()

    assert adapter.list_ids() == ["BOUNDARY-001"]


def test_adapter_delete_does_not_delete_unrelated_files(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    adapter.save(_task())
    unrelated = tmp_path / "README.txt"
    unrelated.write_text("keep", encoding="utf-8")

    adapter.delete("BOUNDARY-001")

    assert unrelated.exists()
