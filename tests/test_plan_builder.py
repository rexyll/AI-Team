import pytest

from runtime.plan_builder import (
    PlanBuilder,
    build_task_manager,
    build_tasks,
)
from runtime.task import Task
from runtime.task_manager import TaskManager


def _valid_plan():
    return {
        "project": "个人记账软件",
        "summary": "实现一个简单的个人记账系统",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "数据库 Schema 设计",
                "description": "设计 SQLite 数据库结构。",
                "role": "architect",
                "dependencies": [],
            },
            {
                "id": "TASK-002",
                "title": "数据模型开发",
                "description": "根据数据库设计实现数据模型。",
                "role": "developer",
                "dependencies": [
                    "TASK-001",
                ],
            },
            {
                "id": "TASK-003",
                "title": "编写测试",
                "description": "为数据模型和 DAO 编写测试。",
                "role": "tester",
                "dependencies": [
                    "TASK-002",
                ],
            },
            {
                "id": "TASK-004",
                "title": "代码审查",
                "description": "对开发结果进行代码审查。",
                "role": "reviewer",
                "dependencies": [
                    "TASK-002",
                ],
            },
        ],
    }


def test_build_tasks_returns_task_objects():
    plan = _valid_plan()

    tasks = build_tasks(plan)

    assert isinstance(tasks, list)
    assert len(tasks) == 4

    assert all(
        isinstance(task, Task)
        for task in tasks
    )


def test_build_tasks_preserves_task_fields():
    plan = _valid_plan()

    tasks = build_tasks(plan)

    task = tasks[0]

    assert task.id == "TASK-001"
    assert task.title == "数据库 Schema 设计"
    assert task.description == "设计 SQLite 数据库结构。"
    assert task.role == "architect"
    assert task.dependencies == []


def test_build_tasks_preserves_dependency_order():
    plan = _valid_plan()

    tasks = build_tasks(plan)

    assert tasks[1].dependencies == [
        "TASK-001",
    ]

    assert tasks[2].dependencies == [
        "TASK-002",
    ]

    assert tasks[3].dependencies == [
        "TASK-002",
    ]


def test_build_tasks_initial_status_is_pending():
    plan = _valid_plan()

    tasks = build_tasks(plan)

    assert all(
        task.status == "pending"
        for task in tasks
    )


def test_build_tasks_does_not_share_dependency_list():
    plan = _valid_plan()

    tasks = build_tasks(plan)

    tasks[1].dependencies.append("TASK-999")

    assert plan["tasks"][1]["dependencies"] == [
        "TASK-001",
    ]


def test_build_tasks_validates_plan():
    plan = _valid_plan()

    del plan["summary"]

    with pytest.raises(ValueError):
        build_tasks(plan)


def test_build_tasks_rejects_invalid_plan_type():
    with pytest.raises(TypeError):
        build_tasks([])


def test_build_tasks_rejects_invalid_task_role():
    plan = _valid_plan()

    plan["tasks"][0]["role"] = "invalid-role"

    with pytest.raises(ValueError):
        build_tasks(plan)


def test_build_tasks_rejects_unknown_dependency():
    plan = _valid_plan()

    plan["tasks"][1]["dependencies"] = [
        "TASK-999",
    ]

    with pytest.raises(ValueError):
        build_tasks(plan)


def test_build_tasks_rejects_duplicate_task_id():
    plan = _valid_plan()

    plan["tasks"][1]["id"] = "TASK-001"

    with pytest.raises(ValueError):
        build_tasks(plan)


def test_build_tasks_rejects_circular_dependency():
    plan = _valid_plan()

    plan["tasks"][0]["dependencies"] = [
        "TASK-004",
    ]

    with pytest.raises(ValueError):
        build_tasks(plan)


def test_plan_builder_class_builds_tasks():
    plan = _valid_plan()

    builder = PlanBuilder()

    tasks = builder.build_tasks(plan)

    assert len(tasks) == 4
    assert tasks[0].id == "TASK-001"


def test_build_task_manager_returns_task_manager():
    plan = _valid_plan()

    manager = build_task_manager(plan)

    assert isinstance(
        manager,
        TaskManager,
    )

    assert len(
        manager.get_all_tasks()
    ) == 4


def test_plan_builder_build_task_manager():
    plan = _valid_plan()

    builder = PlanBuilder()

    manager = builder.build_task_manager(plan)

    assert isinstance(
        manager,
        TaskManager,
    )

    task = manager.get_task("TASK-002")

    assert task.role == "developer"
    assert task.dependencies == [
        "TASK-001",
    ]


def test_build_task_manager_initializes_all_tasks_as_pending():
    plan = _valid_plan()

    manager = build_task_manager(plan)

    tasks = manager.get_all_tasks()

    assert all(
        task.status == "pending"
        for task in tasks
    )


def test_build_tasks_returns_independent_task_objects():
    plan = _valid_plan()

    tasks1 = build_tasks(plan)
    tasks2 = build_tasks(plan)

    assert tasks1 is not tasks2
    assert tasks1[0] is not tasks2[0]

    tasks1[0].title = "Changed"

    assert tasks2[0].title == "数据库 Schema 设计"