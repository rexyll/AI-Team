import json

import pytest

from runtime.task import Task
from runtime.task_persistence import TaskPersistenceAdapter


def _task(task_id: str = "PERSIST-001") -> Task:
    return Task(
        id=task_id,
        title="Persistence adapter",
        description="verify persistence adapter boundary",
        role="developer",
        dependencies=["TASK-001"],
        max_retries=2,
    )


def test_adapter_round_trip_preserves_task(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    task = _task()
    task.retry_attempt = 1

    adapter.save(task)
    restored = adapter.load(task.id)

    assert restored.to_dict() == task.to_dict()


def test_adapter_does_not_accept_non_task_payload(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)

    with pytest.raises(TypeError):
        adapter.save({"id": "PERSIST-001"})  # type: ignore[arg-type]


def test_adapter_missing_task_is_explicit(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)

    with pytest.raises(KeyError):
        adapter.load("MISSING-001")


def test_adapter_rejects_corrupt_payload(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    path = tmp_path / "PERSIST-001.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError):
        adapter.load("PERSIST-001")


def test_adapter_rejects_duplicate_identity_without_overwrite(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    task = _task()
    adapter.save(task)

    with pytest.raises(FileExistsError):
        adapter.save(task)


def test_adapter_list_ids_is_stable(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    adapter.save(_task("PERSIST-002"))
    adapter.save(_task("PERSIST-001"))

    assert adapter.list_ids() == ["PERSIST-001", "PERSIST-002"]


def test_adapter_delete_is_explicit(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    adapter.save(_task())

    adapter.delete("PERSIST-001")

    with pytest.raises(KeyError):
        adapter.load("PERSIST-001")


def test_adapter_persists_json_only(tmp_path):
    adapter = TaskPersistenceAdapter(tmp_path)
    adapter.save(_task())

    payload = json.loads((tmp_path / "PERSIST-001.json").read_text(encoding="utf-8"))
    assert payload["id"] == "PERSIST-001"
    assert isinstance(payload, dict)
