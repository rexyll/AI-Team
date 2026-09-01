import pytest

from runtime.multi_project_scheduler import MultiProjectScheduler, ProjectSchedulingRequest
from runtime.project_scheduler import ProjectExecutionScope, ProjectScheduler
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_status import TaskStatus


def _task(task_id: str, project_id: str, *, status: str = TaskStatus.PENDING.value) -> Task:
    return Task(
        task_id,
        task_id,
        "task",
        "developer",
        status=status,
        context={"project_id": project_id},
    )


def _scheduler(project_id: str, task_id: str) -> ProjectScheduler:
    return ProjectScheduler(
        ProjectExecutionScope(project_id),
        [_task(task_id, project_id)],
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)),
    )


def test_project_ids_are_sorted_for_deterministic_arbitration() -> None:
    coordinator = MultiProjectScheduler([
        _scheduler("P2", "B"),
        _scheduler("P1", "A"),
    ])
    assert coordinator.project_ids == ("P1", "P2")
    assert coordinator.next_admissible() == ProjectSchedulingRequest(ProjectExecutionScope("P1"), "A")


def test_projects_keep_independent_resource_budgets() -> None:
    first = _scheduler("P1", "A")
    second = _scheduler("P2", "B")
    coordinator = MultiProjectScheduler([first, second])

    first_request = coordinator.next_admissible()
    assert first_request is not None
    first_decision = coordinator.decide(first_request)
    assert first_decision.admitted is True
    assert second.decide(ProjectSchedulingRequest(ProjectExecutionScope("P2"), "B")).admitted is True


def test_unknown_project_is_rejected_without_mutating_registered_schedulers() -> None:
    coordinator = MultiProjectScheduler([_scheduler("P1", "A")])
    with pytest.raises(KeyError, match="Unknown project"):
        coordinator.decide(ProjectSchedulingRequest(ProjectExecutionScope("P2"), "B"))


def test_scope_mismatch_is_rejected() -> None:
    coordinator = MultiProjectScheduler([_scheduler("P1", "A")])
    with pytest.raises(ValueError, match="does not match"):
        coordinator.decide(ProjectSchedulingRequest(ProjectExecutionScope("P2"), "A"))


def test_empty_coordinator_has_no_next_task() -> None:
    assert MultiProjectScheduler([]).next_admissible() is None
