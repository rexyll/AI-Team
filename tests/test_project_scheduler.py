import pytest

from runtime.project_scheduler import ProjectAdmissionDecision, ProjectExecutionScope, ProjectScheduler
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_status import TaskStatus


def _task(task_id: str, *, project_id: str = "P1", status: str = TaskStatus.PENDING.value, dependencies=()):
    return Task(
        task_id,
        task_id,
        "task",
        "developer",
        status=status,
        dependencies=list(dependencies),
        context={"project_id": project_id},
    )


def test_scope_is_immutable_and_normalizes_identity() -> None:
    scope = ProjectExecutionScope("  P1  ")
    assert scope.project_id == "P1"
    with pytest.raises(Exception):
        scope.project_id = "P2"


def test_scheduler_admits_dependency_ready_tasks_within_budget() -> None:
    tasks = [_task("A", status=TaskStatus.COMPLETED.value), _task("B", dependencies=("A",))]
    scheduler = ProjectScheduler(
        ProjectExecutionScope("P1"),
        tasks,
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)),
    )
    assert [task.id for task in scheduler.admissible_tasks()] == ["B"]
    assert scheduler.decide("B") == ProjectAdmissionDecision(ProjectExecutionScope("P1"), "B", True, None)


def test_scheduler_rejects_cross_project_tasks() -> None:
    with pytest.raises(ValueError, match="belongs to project"):
        ProjectScheduler(
            ProjectExecutionScope("P1"),
            [_task("A", project_id="P2")],
            ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)),
        )


def test_admission_decision_does_not_mutate_task_status() -> None:
    task = _task("A")
    scheduler = ProjectScheduler(
        ProjectExecutionScope("P1"),
        [task],
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)),
    )
    decision = scheduler.decide("A")
    assert decision.admitted is True
    assert task.status == TaskStatus.PENDING.value


def test_scheduler_honors_concurrency_budget() -> None:
    task = _task("A")
    governor = ResourceGovernor(
        ResourceLimits(max_concurrent_tasks=1),
    ).start_task()
    scheduler = ProjectScheduler(ProjectExecutionScope("P1"), [task], governor)
    decision = scheduler.decide("A")
    assert decision.admitted is False
    assert decision.reason == "concurrency resource limit exceeded"
