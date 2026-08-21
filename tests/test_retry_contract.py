import pytest

from runtime.task_manager import TaskManager
from runtime.task import Task


def _manager() -> TaskManager:
    manager = TaskManager()
    manager.add_task(
        Task(
            id="RETRY-001",
            title="retry contract",
            description="retry contract",
            role="developer",
        )
    )
    return manager


def test_task_starts_with_zero_retry_attempts():
    task = _manager().get_task("RETRY-001")
    assert task.retry_attempt == 0
    assert task.max_retries == 0
    assert task.retry_history == []


def test_retry_attempt_requires_explicit_retry_budget():
    task = _manager().get_task("RETRY-001")

    with pytest.raises(ValueError):
        task.configure_retry(max_retries=-1)


def test_retry_attempt_is_separate_from_task_status_history():
    task = _manager().get_task("RETRY-001")
    task.configure_retry(max_retries=2)

    task.record_retry_attempt(reason="transient failure", retryable=True)

    assert task.retry_attempt == 1
    assert task.retry_history == [
        {
            "attempt": 1,
            "reason": "transient failure",
            "retryable": True,
        }
    ]
    assert task.status_history == []


def test_retry_budget_is_enforced():
    task = _manager().get_task("RETRY-001")
    task.configure_retry(max_retries=1)
    task.record_retry_attempt(reason="temporary failure", retryable=True)

    with pytest.raises(RuntimeError):
        task.record_retry_attempt(reason="temporary failure", retryable=True)


def test_non_retryable_failure_cannot_create_retry_attempt():
    task = _manager().get_task("RETRY-001")
    task.configure_retry(max_retries=3)

    with pytest.raises(RuntimeError):
        task.record_retry_attempt(reason="invalid contract", retryable=False)

    assert task.retry_attempt == 0
    assert task.retry_history == []


def test_retry_attempt_does_not_mutate_successful_peer_task():
    manager = _manager()
    manager.add_task(
        Task(
            id="RETRY-002",
            title="peer",
            description="peer",
            role="developer",
            status="completed",
        )
    )

    task = manager.get_task("RETRY-001")
    peer = manager.get_task("RETRY-002")
    task.configure_retry(max_retries=2)
    task.record_retry_attempt(reason="temporary failure", retryable=True)

    assert peer.status == "completed"
    assert peer.retry_attempt == 0
    assert peer.retry_history == []
