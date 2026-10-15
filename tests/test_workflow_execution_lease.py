from threading import Barrier, Lock, Thread
from time import sleep

import pytest

from runtime.task_lease import LeaseUnavailable
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.workflow_execution_lease import WorkflowExecutionLease


def test_only_one_worker_can_enter_shared_workflow_execution_boundary():
    manager = FencedTaskLeaseManager(default_ttl_seconds=5)
    first = WorkflowExecutionLease(manager, owner_id="worker-a")
    second = WorkflowExecutionLease(manager, owner_id="worker-b")
    barrier = Barrier(2)
    entered = []
    lock = Lock()
    failures = []

    def run(guard):
        try:
            barrier.wait()
            guard.run("TASK-1", lambda lease: (entered.append(lease.owner_id), sleep(0.05)))
        except Exception as exc:
            failures.append(exc)

    threads = [Thread(target=run, args=(first,)), Thread(target=run, args=(second,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(entered) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], LeaseUnavailable)


def test_failed_execution_still_releases_lease_for_next_worker():
    manager = FencedTaskLeaseManager(default_ttl_seconds=5)
    first = WorkflowExecutionLease(manager, owner_id="worker-a")
    second = WorkflowExecutionLease(manager, owner_id="worker-b")

    with pytest.raises(RuntimeError, match="boom"):
        first.run("TASK-1", lambda lease: (_ for _ in ()).throw(RuntimeError("boom")))

    result = second.run("TASK-1", lambda lease: lease.owner_id)
    assert result == "worker-b"


def test_cleanup_of_expired_execution_does_not_mask_success():
    from datetime import datetime, timedelta, timezone

    manager = FencedTaskLeaseManager(default_ttl_seconds=1)
    guard = WorkflowExecutionLease(manager, owner_id="worker-a")
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)

    with guard.hold("TASK-1", now=t0) as lease:
        manager._leases.expire(now=t0 + timedelta(seconds=2))
        assert lease.owner_id == "worker-a"
