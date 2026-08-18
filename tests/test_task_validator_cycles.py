import pytest

from runtime.task_validator import validate_plan


def make_plan(tasks):
    return {
        "project": "cycle-test",
        "summary": "dependency validation",
        "tasks": tasks,
    }


def task(task_id, dependencies=None):
    return {
        "id": task_id,
        "title": task_id,
        "description": "test task",
        "role": "developer",
        "dependencies": dependencies or [],
    }


def test_validator_rejects_direct_cycle():
    plan = make_plan([
        task("TASK-001", ["TASK-002"]),
        task("TASK-002", ["TASK-001"]),
    ])

    with pytest.raises(ValueError, match="Circular task dependency detected"):
        validate_plan(plan)


def test_validator_rejects_indirect_cycle():
    plan = make_plan([
        task("TASK-001", ["TASK-003"]),
        task("TASK-002", ["TASK-001"]),
        task("TASK-003", ["TASK-002"]),
    ])

    with pytest.raises(ValueError, match="Circular task dependency detected"):
        validate_plan(plan)


def test_validator_accepts_acyclic_dependencies():
    plan = make_plan([
        task("TASK-001"),
        task("TASK-002", ["TASK-001"]),
        task("TASK-003", ["TASK-001", "TASK-002"]),
    ])

    validate_plan(plan)
