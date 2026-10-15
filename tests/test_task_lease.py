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


def test_expiry_is_exact_at_deadline_and_allows_reacquisition():
    manager = TaskLeaseManager(default_ttl_seconds=10)
    first = manager.acquire("TASK-1", "worker-a", now=BASE)
    assert manager.get("TASK-1", now=first.expires_at) is None
    replacement = manager.acquire("TASK-1", "worker-b", now=first.expires_at)
    assert replacement.owner_id == "worker-b"
    assert replacement.token != first.token


def test_expire_removes_only_stale_leases_atomically():
    manager = TaskLeaseManager(default_ttl_seconds=10)
    stale = manager.acquire("TASK-STALE", "worker-a", now=BASE)
    live = manager.acquire("TASK-LIVE", "worker-b", now=BASE)
    expired = manager.expire(now=BASE + timedelta(seconds=10))
    assert [lease.task_id for lease in expired] == [stale.task_id, live.task_id]
    assert manager.get("TASK-STALE", now=BASE + timedelta(seconds=10)) is None
    assert manager.get("TASK-LIVE", now=BASE + timedelta(seconds=10)) is None


def test_expire_does_not_remove_live_lease():
    manager = TaskLeaseManager(default_ttl_seconds=10)
    live = manager.acquire("TASK-LIVE", "worker-a", now=BASE)
    assert manager.expire(now=BASE + timedelta(seconds=9)) == ()
    assert manager.get("TASK-LIVE", now=BASE + timedelta(seconds=9)) == live


def test_expired_owner_cannot_release_a_replacement_lease():
    manager = TaskLeaseManager(default_ttl_seconds=10)
    stale = manager.acquire("TASK-1", "worker-a", now=BASE)
    replacement = manager.acquire("TASK-1", "worker-b", now=stale.expires_at)
    with pytest.raises(LeaseOwnershipError):
        manager.release("TASK-1", "worker-a", stale.token)
    manager.release("TASK-1", "worker-b", replacement.token)


def test_lease_tokens_are_unique_between_acquisitions():
    manager = TaskLeaseManager()
    first = manager.acquire("TASK-1", "worker-a", now=BASE)
    manager.release("TASK-1", "worker-a", first.token)
    second = manager.acquire("TASK-1", "worker-b", now=BASE)
    assert first.token != second.token
