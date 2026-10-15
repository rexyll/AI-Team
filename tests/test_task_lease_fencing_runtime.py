from datetime import datetime, timedelta, timezone

import pytest

from runtime.task_lease import LeaseOwnershipError
from runtime.task_lease_fencing import FencedTaskLeaseManager


def test_expired_owner_gets_new_monotonic_generation():
    manager = FencedTaskLeaseManager(default_ttl_seconds=10)
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)
    first = manager.acquire("TASK-1", "worker-a", now=t0)
    second = manager.acquire("TASK-1", "worker-b", now=t0 + timedelta(seconds=11))
    assert second.generation == first.generation + 1
    with pytest.raises(LeaseOwnershipError):
        manager.assert_current("TASK-1", "worker-a", first.lease.token, first.generation, now=t0 + timedelta(seconds=11))


def test_stale_generation_cannot_release_current_owner():
    manager = FencedTaskLeaseManager(default_ttl_seconds=10)
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)
    first = manager.acquire("TASK-1", "worker-a", now=t0)
    second = manager.acquire("TASK-1", "worker-b", now=t0 + timedelta(seconds=11))
    with pytest.raises(LeaseOwnershipError):
        manager.release("TASK-1", "worker-b", second.lease.token, first.generation)
    assert manager.assert_current("TASK-1", "worker-b", second.lease.token, second.generation, now=t0 + timedelta(seconds=11)) is None
