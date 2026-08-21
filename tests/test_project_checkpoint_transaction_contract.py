from __future__ import annotations

import json

import pytest

from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def _plan() -> dict:
    return {
        "project": "checkpoint-demo",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "demo",
                "description": "checkpoint",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id="TASK-001",
                title="demo",
                description="checkpoint",
                role="developer",
                status="completed",
            )
        ]
    )


def test_checkpoint_requires_complete_project_result(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    result = ProjectResult.from_task_manager(manager, project="checkpoint-demo")
    adapter.save(
        "PROJECT-001",
        plan=_plan(),
        task_manager=manager,
        result=result,
    )

    with pytest.raises(TypeError, match="result must be a ProjectResult"):
        adapter.checkpoint(
            "PROJECT-001",
            plan=_plan(),
            task_manager=manager,
            result=None,
        )


def test_checkpoint_rejects_inconsistent_result_without_replacing_snapshot(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    result = ProjectResult.from_task_manager(manager, project="checkpoint-demo")
    adapter.save(
        "PROJECT-002",
        plan=_plan(),
        task_manager=manager,
        result=result,
    )
    path = tmp_path / "PROJECT-002.json"
    before = path.read_bytes()

    inconsistent = ProjectResult(
        project="checkpoint-demo",
        success=False,
        status="failed",
        total_tasks=1,
        completed_tasks=0,
        failed_tasks=("TASK-001",),
        blocked_tasks=(),
    )

    with pytest.raises(ValueError, match="result mismatch"):
        adapter.checkpoint(
            "PROJECT-002",
            plan=_plan(),
            task_manager=manager,
            result=inconsistent,
        )

    assert path.read_bytes() == before
    restored = adapter.load("PROJECT-002")
    assert restored.result == result


def test_checkpoint_commits_task_state_and_result_as_one_snapshot(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = TaskManager(
        [
            Task(
                id="TASK-001",
                title="demo",
                description="checkpoint",
                role="developer",
                status="ready",
            )
        ]
    )
    initial_result = ProjectResult.from_task_manager(manager, project="checkpoint-demo")
    adapter.save(
        "PROJECT-003",
        plan=_plan(),
        task_manager=manager,
        result=initial_result,
    )

    manager.mark_running("TASK-001")
    manager.mark_completed("TASK-001", {"status": "completed", "agent": "developer", "task_id": "TASK-001"})
    checkpoint_result = ProjectResult.from_task_manager(manager, project="checkpoint-demo")

    adapter.checkpoint(
        "PROJECT-003",
        plan=_plan(),
        task_manager=manager,
        result=checkpoint_result,
    )

    payload = json.loads((tmp_path / "PROJECT-003.json").read_text(encoding="utf-8"))
    assert payload["tasks"][0]["status"] == "completed"
    assert payload["result"] == checkpoint_result.to_dict()

    restored = adapter.load("PROJECT-003")
    assert restored.task_manager.get_task("TASK-001").status == "completed"
    assert restored.result == checkpoint_result
