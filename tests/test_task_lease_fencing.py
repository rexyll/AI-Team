from datetime import datetime, timedelta, timezone

import pytest

from runtime.task_lease import LeaseOwnershipError, TaskLeaseManager


def test_stale_worker_cannot_release_new_generation_after_expiry():
    manager = TaskLeaseManager(default_ttl_seconds=10)
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)
    first = manager.acquire("TASK-1", "worker-a", now=t0)
    second = manager.acquire("TASK-1", "worker-b", now=t0 + timedelta(seconds=11))

    assert first.token != second.token
    with pytest.raises(LeaseOwnershipError):
        manager.release("TASK-1", "worker-a", first.token)
    assert manager.get("TASK-1", now=t0 + timedelta(seconds=11)) == second


def test_stale_worker_cannot_renew_new_generation():
    manager = TaskLeaseManager(default_ttl_seconds=10)
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)
    first = manager.acquire("TASK-1", "worker-a", now=t0)
    second = manager.acquire("TASK-1", "worker-b", now=t0 + timedelta(seconds=11))

    with pytest.raises(LeaseOwnershipError):
        manager.renew("TASK-1", "worker-a", first.token, now=t0 + timedelta(seconds=11))
    assert manager.get("TASK-1", now=t0 + timedelta(seconds=11)) == second
