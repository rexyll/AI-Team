from runtime.crash_recovery import (
    RecoveryAction,
    decide_crash_recovery,
    recoverable_after_crash,
    recovery_snapshot,
)
from runtime.task import Task
from runtime.task_status import TaskStatus


def _task(status: str) -> Task:
    return Task(id="TASK-001", title="test", description="test", role="developer", status=status)


def test_terminal_states_are_never_replayed():
    for status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
        decision = decide_crash_recovery(_task(status))
        assert decision.action is RecoveryAction.NOOP
        assert decision.resource_reconciliation_required is False
        assert recoverable_after_crash(_task(status)) is False


def test_interrupted_execution_states_are_requeued_and_require_resource_reconciliation():
    for status in (
        TaskStatus.RUNNING.value,
        TaskStatus.REVIEW_PENDING.value,
        TaskStatus.REVIEWING.value,
        TaskStatus.REVISION.value,
    ):
        decision = decide_crash_recovery(_task(status))
        assert decision.action is RecoveryAction.REQUEUE
        assert decision.resource_reconciliation_required is True
        assert recoverable_after_crash(_task(status)) is True


def test_persisted_non_running_states_are_restored_without_replay():
    for status in (
        TaskStatus.PENDING.value,
        TaskStatus.READY.value,
        TaskStatus.BLOCKED.value,
    ):
        decision = decide_crash_recovery(_task(status))
        assert decision.action is RecoveryAction.RESTORE
        assert decision.resource_reconciliation_required is False


def test_recovery_decision_does_not_mutate_task():
    task = _task(TaskStatus.RUNNING.value)
    task.configure_retry(max_retries=2)
    task.record_retry_attempt(reason="previous failure", retryable=True)
    before = task.to_dict()

    decision = decide_crash_recovery(task)

    assert decision.action is RecoveryAction.REQUEUE
    assert task.to_dict() == before


def test_recovery_snapshot_is_persistence_safe_and_preserves_retry_boundary():
    task = _task(TaskStatus.RUNNING.value)
    task.configure_retry(max_retries=3)
    task.record_retry_attempt(reason="previous failure", retryable=True)

    snapshot = recovery_snapshot(task)

    assert snapshot["task_id"] == "TASK-001"
    assert snapshot["previous_status"] == TaskStatus.RUNNING.value
    assert snapshot["action"] == "requeue"
    assert snapshot["retry_attempt"] == 1
    assert snapshot["max_retries"] == 3
    assert snapshot["cancellation_requested"] is False
