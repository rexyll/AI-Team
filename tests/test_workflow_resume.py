import pytest

from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.workflow_resume import WorkflowResumeError, WorkflowResumePlanner


def _task(task_id: str, status: str) -> Task:
    task = Task(task_id, task_id, "resume", "developer")
    task.status = status
    return task


def test_resume_planning_is_idempotent_and_does_not_mutate_tasks():
    tasks = [
        _task("TASK-DONE", TaskStatus.COMPLETED.value),
        _task("TASK-READY", TaskStatus.READY.value),
    ]
    planner = WorkflowResumePlanner()
    first = planner.plan(tasks)
    second = planner.plan(tasks)
    assert first == second
    assert first.resumable_task_ids == ("TASK-READY",)
    assert [task.status for task in tasks] == ["completed", "ready"]
    assert [task.status_history for task in tasks] == [[], []]


def test_resume_planning_rejects_duplicate_task_ids():
    task = _task("TASK-DUP", TaskStatus.READY.value)
    with pytest.raises(WorkflowResumeError):
        WorkflowResumePlanner().plan([task, task])
