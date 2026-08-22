from __future__ import annotations

import json

import pytest

import runtime.project_persistence as project_persistence
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def _plan() -> dict:
    return {
        "project": "atomic-demo",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "demo",
                "description": "atomic persistence",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def _manager(status: str = "ready") -> TaskManager:
    return TaskManager(
        [
            Task(
                id="TASK-001",
                title="demo",
                description="atomic persistence",
                role="developer",
                status=status,
            )
        ]
    )


def _result(manager: TaskManager) -> ProjectResult:
    return ProjectResult.from_task_manager(manager, project="atomic-demo")


def _save_initial(adapter: ProjectPersistenceAdapter, project_id: str = "PROJECT-001") -> bytes:
    manager = _manager()
    adapter.save(
        project_id,
        plan=_plan(),
        task_manager=manager,
        result=_result(manager),
    )
    return (adapter.root / f"{project_id}.json").read_bytes()


def test_update_replace_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    adapter = ProjectPersistenceAdapter(tmp_path)
    before = _save_initial(adapter)

    replacement_manager = _manager("completed")
    replacement_result = _result(replacement_manager)

    def fail_replace(source, target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(project_persistence.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        adapter.update(
            "PROJECT-001",
            plan=_plan(),
            task_manager=replacement_manager,
            result=replacement_result,
        )

    path = tmp_path / "PROJECT-001.json"
    assert path.read_bytes() == before
    assert adapter.load("PROJECT-001").result is not None
    assert adapter.load("PROJECT-001").task_manager.get_task("TASK-001").status == "ready"
    assert not list(tmp_path.glob(".PROJECT-001-*.tmp"))


def test_checkpoint_replace_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    adapter = ProjectPersistenceAdapter(tmp_path)
    before = _save_initial(adapter, "PROJECT-002")

    replacement_manager = _manager("completed")
    replacement_result = _result(replacement_manager)

    def fail_replace(source, target):
        raise OSError("injected checkpoint replace failure")

    monkeypatch.setattr(project_persistence.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected checkpoint replace failure"):
        adapter.checkpoint(
            "PROJECT-002",
            plan=_plan(),
            task_manager=replacement_manager,
            result=replacement_result,
        )

    path = tmp_path / "PROJECT-002.json"
    assert path.read_bytes() == before
    restored = adapter.load("PROJECT-002")
    assert restored.task_manager.get_task("TASK-001").status == "ready"
    assert restored.result == _result(_manager())
    assert not list(tmp_path.glob(".PROJECT-002-*.tmp"))


def test_atomic_write_serialization_failure_removes_staged_file_and_preserves_snapshot(
    tmp_path, monkeypatch
):
    adapter = ProjectPersistenceAdapter(tmp_path)
    before = _save_initial(adapter, "PROJECT-003")

    real_dump = project_persistence.json.dump

    def fail_dump(payload, handle, **kwargs):
        real_dump(payload, handle, **kwargs)
        raise ValueError("injected serialization failure")

    monkeypatch.setattr(project_persistence.json, "dump", fail_dump)

    with pytest.raises(ValueError, match="injected serialization failure"):
        adapter.update(
            "PROJECT-003",
            plan=_plan(),
            task_manager=_manager("completed"),
            result=_result(_manager("completed")),
        )

    path = tmp_path / "PROJECT-003.json"
    assert path.read_bytes() == before
    assert adapter.load("PROJECT-003").task_manager.get_task("TASK-001").status == "ready"
    assert not list(tmp_path.glob(".PROJECT-003-*.tmp"))


def test_successful_update_leaves_only_committed_snapshot(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    _save_initial(adapter, "PROJECT-004")

    manager = _manager("completed")
    adapter.update(
        "PROJECT-004",
        plan=_plan(),
        task_manager=manager,
        result=_result(manager),
    )

    payload = json.loads((tmp_path / "PROJECT-004.json").read_text(encoding="utf-8"))
    assert payload["tasks"][0]["status"] == "completed"
    assert payload["result"] == _result(manager).to_dict()
    assert not list(tmp_path.glob(".PROJECT-004-*.tmp"))
