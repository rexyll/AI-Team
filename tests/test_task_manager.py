# from agents.planner import create_plan
# from runtime.plan_loader import load_tasks
# from runtime.task_manager import TaskManager


# requirement = """
# 开发一个个人记账软件。

# 要求：

# 1. 支持收入和支出记录
# 2. 支持分类
# 3. 支持按月份统计
# 4. 使用 SQLite
# 5. 提供 REST API
# 6. 提供 Web 页面
# 7. 编写自动化测试
# """


# plan = create_plan(requirement)

# tasks = load_tasks(plan)

# manager = TaskManager(tasks)


# print()
# print("=" * 60)
# print("INITIAL TASK STATUS")
# print("=" * 60)

# for task in manager.get_all_tasks():
#     print(
#         f"{task.id:<10}"
#         f"{task.status:<12}"
#         f"{task.role:<12}"
#         f"{task.title}"
#     )


# print()
# print("=" * 60)
# print("READY TASKS")
# print("=" * 60)


# ready_tasks = manager.get_ready_tasks()


# if ready_tasks:

#     task = ready_tasks[0]

#     print()
#     print(
#         f"开始执行：{task.id}"
#     )

#     manager.mark_running(task.id)

#     print(
#         f"状态：{task.status}"
#     )

#     manager.mark_completed(
#         task.id,
#         {
#             "message": "任务完成"
#         },
#     )

#     print(
#         f"状态：{task.status}"
#     )


# print()
# print("=" * 60)
# print("NEXT READY TASKS")
# print("=" * 60)

# for task in manager.get_ready_tasks():

#     print(
#         f"{task.id:<10}"
#         f"{task.role:<12}"
#         f"{task.title}"
#     )

import pytest


from runtime.task import Task
from runtime.task_manager import TaskManager


def test_failed_dependency_blocks_task():

    tasks = [
        Task(
            id="TASK-001",
            title="架构设计",
            description="数据库设计",
            role="architect",
        ),
        Task(
            id="TASK-002",
            title="开发",
            description="实现数据库",
            role="developer",
            dependencies=["TASK-001"],
        ),
    ]

    manager = TaskManager(tasks)

    ready = manager.get_ready_tasks()

    assert len(ready) == 1
    assert ready[0].id == "TASK-001"

    manager.mark_running("TASK-001")

    manager.mark_failed(
        "TASK-001",
        "Architect failed",
    )

    ready = manager.get_ready_tasks()

    assert len(ready) == 0

    task2 = manager.get_task("TASK-002")

    assert task2.status == "blocked"

    assert "TASK-001" in task2.error
    
    
    
def test_missing_dependency_blocks_task():

    task = Task(
        id="TASK-002",
        title="开发",
        description="实现数据库",
        role="developer",
        dependencies=["TASK-999"],
    )

    manager = TaskManager([task])

    ready = manager.get_ready_tasks()

    assert len(ready) == 0

    task = manager.get_task("TASK-002")

    assert task.status == "blocked"

    assert "TASK-999" in task.error
    
def test_task_manager_uses_valid_status_transitions():
    task = Task(
        id="TASK-STATE-001",
        title="state",
        description="state",
        role="developer",
        status="ready",
    )

    manager = TaskManager([task])

    manager.mark_running(task.id)

    assert task.status == "running"
    
def test_task_manager_rejects_invalid_transition():
    task = Task(
        id="TASK-STATE-002",
        title="state",
        description="state",
        role="developer",
        status="ready",
    )

    manager = TaskManager([task])

    with pytest.raises(ValueError):
        manager.mark_reviewing(task.id)