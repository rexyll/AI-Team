from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from runtime.lease_guarded_executor import LeaseGuardedExecutor
from runtime.task_lease import LeaseUnavailable, TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.workflow_execution_lease import WorkflowExecutionLease


def test_only_one_concurrent_worker_enters_guarded_execution():
    execution = WorkflowExecutionLease(FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30)), owner_id="worker-a")
    other = WorkflowExecutionLease(execution.lease_manager, owner_id="worker-b")
    first_started = Barrier(2)
    entered = []

    def first():
        def action(_lease):
            entered.append("a")
            first_started.wait()
            return "a"
        return LeaseGuardedExecutor(execution).execute("TASK-1", action)

    def second():
        first_started.wait()
        with pytest.raises(LeaseUnavailable):
            return LeaseGuardedExecutor(other).execute("TASK-1", lambda _lease: entered.append("b"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert pool.submit(first).result() == "a"
        pool.submit(second).result()

    assert entered == ["a"]


def test_guarded_execution_releases_after_failure():
    manager = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    first = LeaseGuardedExecutor(WorkflowExecutionLease(manager, owner_id="worker-a"))
    second = LeaseGuardedExecutor(WorkflowExecutionLease(manager, owner_id="worker-b"))

    with pytest.raises(RuntimeError):
        first.execute("TASK-1", lambda _lease: (_ for _ in ()).throw(RuntimeError("boom")))

    assert second.execute("TASK-1", lambda _lease: "recovered") == "recovered"
