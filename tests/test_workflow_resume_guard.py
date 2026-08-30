import pytest

from runtime.task import Task
from runtime.workflow_resume_guard import WorkflowResumeError, WorkflowResumeGuard


def _task(task_id: str, status: str) -> Task:
    task = Task(task_id, task_id, "resume", "developer")
    task.status = status
    return task


def test_completed_task_is_never_resumable():
    task = _task("DONE", "completed")
    decision = WorkflowResumeGuard().decide(task)
    assert decision.resumable is False
    assert decision.reason == "already_completed"
    with pytest.raises(WorkflowResumeError):
        WorkflowResumeGuard().require_resumable(task)


@pytest.mark.parametrize("status", ["ready", "running", "review_pending", "reviewing"])
def test_known_recovery_states_are_resumable(status):
    decision = WorkflowResumeGuard().decide(_task(status.upper(), status))
    assert decision.resumable is True
    assert decision.reason == "safe_to_resume"


def test_unknown_or_terminal_non_completed_state_is_rejected():
    decision = WorkflowResumeGuard().decide(_task("FAILED", "failed"))
    assert decision.resumable is False
    assert decision.reason == "status_not_resumable:failed"
