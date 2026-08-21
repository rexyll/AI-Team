import json

import pytest

from runtime.task import Task


def _task() -> Task:
    task = Task(
        id="PERSIST-001",
        title="Persistence contract",
        description="verify task persistence boundary",
        role="developer",
        dependencies=["TASK-001"],
        max_retries=3,
    )
    task.retry_attempt = 1
    task.status_history = [
        {"from": "pending", "to": "ready"},
        {"from": "ready", "to": "running"},
    ]
    task.context = {"project_name": "AI-Team", "nested": {"value": 1}}
    return task


def test_task_persistence_is_json_serializable():
    task = _task()

    payload = task.to_dict()

    assert json.loads(json.dumps(payload)) == payload


def test_task_persistence_round_trip_preserves_lifecycle_state():
    task = _task()

    restored = Task.from_dict(task.to_dict())

    assert restored.id == task.id
    assert restored.title == task.title
    assert restored.description == task.description
    assert restored.role == task.role
    assert restored.dependencies == task.dependencies
    assert restored.status == task.status
    assert restored.retry_attempt == task.retry_attempt
    assert restored.max_retries == task.max_retries
    assert restored.status_history == task.status_history
    assert restored.context == task.context


def test_task_persistence_does_not_embed_runtime_objects():
    payload = _task().to_dict()

    forbidden = {"agent", "llm", "client", "router", "task_manager", "workflow"}

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in forbidden
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    list(walk(payload))


def test_task_persistence_rejects_missing_identity():
    task = _task()
    payload = task.to_dict()
    payload.pop("id")

    with pytest.raises((KeyError, ValueError, TypeError)):
        Task.from_dict(payload)
