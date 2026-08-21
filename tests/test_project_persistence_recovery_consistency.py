from __future__ import annotations

import json

import pytest

from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def _plan():
    return {
        "project": "Recovery Consistency",
        "summary": "Validate persisted snapshot consistency",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "first",
                "description": "first",
                "role": "developer",
                "dependencies": [],
            },
            {
                "id": "TASK-002",
                "title": "second",
                "description": "second",
                "role": "tester",
                "dependencies": ["TASK-001"],
            },
        ],
    }


def _manager():
    return TaskManager([
        Task(
            id="TASK-001",
            title="first",
            description="first",
            role="developer",
            status="completed",
        ),
        Task(
            id="TASK-002",
            title="second",
            description="second",
            role="tester",
            status="ready",
            dependencies=["TASK-001"],
        ),
    ])


def _save(adapter):
    manager = _manager()
    adapter.save(
        "PROJECT-001",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Recovery Consistency"),
    )


def _read_payload(adapter):
    path = adapter.root / "PROJECT-001.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _write_payload(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_load_accepts_consistent_snapshot(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    _save(adapter)

    snapshot = adapter.load("PROJECT-001")

    assert snapshot.plan == _plan()
    assert snapshot.task_manager.get_task("TASK-001").status == "completed"
    assert snapshot.task_manager.get_task("TASK-002").status == "ready"
    assert snapshot.result == ProjectResult.from_task_manager(
        snapshot.task_manager,
        project="Recovery Consistency",
    )


def test_load_rejects_plan_task_identity_mismatch(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    _save(adapter)
    path, payload = _read_payload(adapter)
    payload["plan"]["tasks"][1]["id"] = "TASK-003"
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="plan/task identity mismatch"):
        adapter.load("PROJECT-001")


def test_load_rejects_plan_task_definition_mismatch(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    _save(adapter)
    path, payload = _read_payload(adapter)
    payload["plan"]["tasks"][0]["role"] = "tester"
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="plan/task mismatch for TASK-001: role"):
        adapter.load("PROJECT-001")


def test_load_rejects_stale_result_snapshot(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    _save(adapter)
    path, payload = _read_payload(adapter)
    payload["result"]["status"] = "completed"
    payload["result"]["success"] = True
    payload["result"]["completed_tasks"] = 2
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="result mismatch"):
        adapter.load("PROJECT-001")
