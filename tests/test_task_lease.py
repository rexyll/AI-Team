from datetime import datetime, timedelta, timezone

import pytest

from runtime.task_lease import LeaseOwnershipError, LeaseUnavailable, TaskLeaseManager


BASE = datetime(2026, 8, 30, tzinfo=timezone.utc)


def test_only_one_live_worker_can_acquire_a_task():
    manager = TaskLeaseManager(default_ttl_seconds=30)
    lease = manager.acquire("TASK-1", "worker-a", now=BASE)
    assert lease.owner_id == "worker-a"
    assert lease.token
    with pytest.raises(LeaseUnavailable):
        manager.acquire("TASK-1", "worker-b", now=BASE + timedelta(seconds=1))


def test_release_requires_exact_owner_and_token():
    manager = TaskLeaseManager()
    lease = manager.acquire("TASK-1", "worker-a", now=BASE)
    with pytest.raises(LeaseOwnershipError):
        manager.release("TASK-1", "worker-b", lease.token)
    with pytest.raises(LeaseOwnershipError):
        manager.release("TASK-1", "worker-a", "wrong-token")
    manager.release("TASK-1", "worker-a", lease.token)
    assert manager.get("TASK-1", now=BASE) is None


def test_expired_lease_no_longer_blocks_acquisition():
    manager = TaskLeaseManager(default_ttl_seconds=10)
    manager.acquire("TASK-1", "worker-a", now=BASE)
    replacement = manager.acquire("TASK-1", "worker-b", now=BASE + timedelta(seconds=10))
    assert replacement.owner_id == "worker-b"
    assert replacement.token


def test_lease_tokens_are_unique_between_acquisitions():
    manager = TaskLeaseManager()
    first = manager.acquire("TASK-1", "worker-a", now=BASE)
    manager.release("TASK-1", "worker-a", first.token)
    second = manager.acquire("TASK-1", "worker-b", now=BASE)
    assert first.token != second.token
