import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus, can_transition


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id="RETRY-LIFE-001",
                title="retry lifecycle",
                description="retry lifecycle",
                role="developer",
                status=TaskStatus.FAILED.value,
                error="temporary failure",
                max_retries=2,
            ),
            Task(
                id="RETRY-LIFE-002",
                title="successful peer",
                description="successful peer",
                role="developer",
                status=TaskStatus.COMPLETED.value,
            ),
        ]
    )


def test_failed_is_not_a_generic_transition_to_ready():
    assert can_transition(TaskStatus.FAILED, TaskStatus.READY) is False


def test_retry_is_explicit_manager_boundary():
    manager = _manager()

    task = manager.retry_task(
        "RETRY-LIFE-001",
        reason="temporary provider failure",
        retryable=True,
    )

    assert task.status == TaskStatus.READY.value
    assert task.error is None
    assert task.retry_attempt == 1
    assert task.retry_history == [
        {
            "attempt": 1,
            "reason": "temporary provider failure",
            "retryable": True,
        }
    ]
    assert task.status_history == [
        {
            "from": TaskStatus.FAILED.value,
            "to": TaskStatus.READY.value,
        }
    ]


def test_retry_requires_failed_task():
    manager = _manager()
    manager.get_task("RETRY-LIFE-002").configure_retry(max_retries=2)

    with pytest.raises(ValueError):
        manager.retry_task(
            "RETRY-LIFE-002",
            reason="should not retry completed task",
            retryable=True,
        )


def test_retry_requires_retryable_failure_and_preserves_failure_on_rejection():
    manager = _manager()
    task = manager.get_task("RETRY-LIFE-001")

    with pytest.raises(RuntimeError):
        manager.retry_task(
            task.id,
            reason="permanent failure",
            retryable=False,
        )

    assert task.status == TaskStatus.FAILED.value
    assert task.retry_attempt == 0
    assert task.retry_history == []
    assert task.error == "temporary failure"
    assert task.status_history == []


def test_retry_budget_exhaustion_preserves_failed_state():
    manager = _manager()
    task = manager.get_task("RETRY-LIFE-001")

    manager.retry_task(
        task.id,
        reason="first temporary failure",
        retryable=True,
    )
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "second temporary failure")
    manager.retry_task(
        task.id,
        reason="second temporary failure",
        retryable=True,
    )
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "third temporary failure")

    with pytest.raises(RuntimeError):
        manager.retry_task(
            task.id,
            reason="retry budget exhausted",
            retryable=True,
        )

    assert task.status == TaskStatus.FAILED.value
    assert task.retry_attempt == 2
    assert len(task.retry_history) == 2
    assert task.error == "third temporary failure"


def test_retry_does_not_mutate_successful_peer():
    manager = _manager()
    peer = manager.get_task("RETRY-LIFE-002")

    manager.retry_task(
        "RETRY-LIFE-001",
        reason="temporary provider failure",
        retryable=True,
    )

    assert peer.status == TaskStatus.COMPLETED.value
    assert peer.retry_attempt == 0
    assert peer.retry_history == []
    assert peer.status_history == []
