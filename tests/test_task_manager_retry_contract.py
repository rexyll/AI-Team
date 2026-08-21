import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id="RETRY-MGR-001",
                title="retry manager contract",
                description="retry manager contract",
                role="developer",
                status=TaskStatus.FAILED.value,
                error="transient failure",
            )
        ]
    )


def test_retry_task_requires_failed_source_state():
    manager = TaskManager(
        [
            Task(
                id="RETRY-MGR-001",
                title="retry manager contract",
                description="retry manager contract",
                role="developer",
                status=TaskStatus.READY.value,
            )
        ]
    )
    task = manager.get_task("RETRY-MGR-001")
    task.configure_retry(max_retries=1)

    with pytest.raises(ValueError):
        manager.retry_task(
            task.id,
            reason="not failed",
            retryable=True,
        )

    assert task.status == TaskStatus.READY.value
    assert task.retry_attempt == 0
    assert task.retry_history == []
    assert task.status_history == []


def test_retry_task_reopens_failed_task_as_ready():
    manager = _manager()
    task = manager.get_task("RETRY-MGR-001")
    task.configure_retry(max_retries=1)

    manager.retry_task(
        task.id,
        reason="provider timeout",
        retryable=True,
    )

    assert task.status == TaskStatus.READY.value
    assert task.error is None
    assert task.retry_attempt == 1
    assert task.retry_history == [
        {
            "attempt": 1,
            "reason": "provider timeout",
            "retryable": True,
        }
    ]
    assert task.status_history == [
        {
            "from": TaskStatus.FAILED.value,
            "to": TaskStatus.READY.value,
        }
    ]


def test_retry_task_enforces_retry_budget_without_mutation():
    manager = _manager()
    task = manager.get_task("RETRY-MGR-001")
    task.configure_retry(max_retries=1)

    manager.retry_task(
        task.id,
        reason="first attempt",
        retryable=True,
    )

    manager.mark_running(task.id)
    manager.mark_failed(task.id, "second failure")

    retry_attempt = task.retry_attempt
    retry_history = list(task.retry_history)
    status_history = list(task.status_history)
    error = task.error

    with pytest.raises(RuntimeError):
        manager.retry_task(
            task.id,
            reason="budget exhausted",
            retryable=True,
        )

    assert task.retry_attempt == retry_attempt
    assert task.retry_history == retry_history
    assert task.status_history == status_history
    assert task.status == TaskStatus.FAILED.value
    assert task.error == error


def test_non_retryable_failure_is_rejected_before_lifecycle_mutation():
    manager = _manager()
    task = manager.get_task("RETRY-MGR-001")
    task.configure_retry(max_retries=2)

    original_history = list(task.status_history)
    original_error = task.error

    with pytest.raises(RuntimeError):
        manager.retry_task(
            task.id,
            reason="permanent failure",
            retryable=False,
        )

    assert task.status == TaskStatus.FAILED.value
    assert task.retry_attempt == 0
    assert task.retry_history == []
    assert task.status_history == original_history
    assert task.error == original_error


def test_retry_attempt_does_not_change_peer_task():
    manager = TaskManager(
        [
            Task(
                id="RETRY-MGR-001",
                title="retry manager contract",
                description="retry manager contract",
                role="developer",
                status=TaskStatus.FAILED.value,
                error="transient failure",
            ),
            Task(
                id="RETRY-MGR-002",
                title="successful peer",
                description="successful peer",
                role="developer",
                status=TaskStatus.COMPLETED.value,
            ),
        ]
    )

    task = manager.get_task("RETRY-MGR-001")
    peer = manager.get_task("RETRY-MGR-002")
    task.configure_retry(max_retries=1)

    manager.retry_task(
        task.id,
        reason="transient failure",
        retryable=True,
    )

    assert peer.status == TaskStatus.COMPLETED.value
    assert peer.status_history == []
    assert peer.retry_attempt == 0
    assert peer.retry_history == []
