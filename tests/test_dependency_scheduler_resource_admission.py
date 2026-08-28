from runtime.dependency_scheduler import DependencyScheduler
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task


def _tasks():
    return [
        Task(id="TASK-001", title="one", description="", role="developer", dependencies=[]),
        Task(id="TASK-002", title="two", description="", role="developer", dependencies=[]),
        Task(id="TASK-003", title="three", description="", role="developer", dependencies=["TASK-001"]),
    ]


def test_admission_limits_ready_tasks_without_mutating_tasks():
    tasks = _tasks()
    scheduler = DependencyScheduler(tasks)
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))

    admitted = scheduler.get_admissible_tasks(governor)

    assert [task.id for task in admitted] == ["TASK-001"]
    assert [task.status for task in tasks] == ["pending", "pending", "pending"]
    assert governor.usage.active_tasks == 0


def test_admission_accounts_for_existing_active_slots():
    scheduler = DependencyScheduler(_tasks())
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=3)).start_task(2)

    admitted = scheduler.get_admissible_tasks(governor)

    assert [task.id for task in admitted] == ["TASK-001"]


def test_full_concurrency_budget_admits_nothing():
    scheduler = DependencyScheduler(_tasks())
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=2)).start_task(2)

    assert scheduler.get_admissible_tasks(governor) == []
