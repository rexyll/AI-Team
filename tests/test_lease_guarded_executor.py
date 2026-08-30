from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from runtime.lease_guarded_executor import LeaseGuardedExecutor
from runtime.task_lease import LeaseUnavailable, TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.workflow_execution_lease import WorkflowExecutionLease


def test_only_one_concurrent_worker_enters_guarded_execution():
    execution = WorkflowExecutionLease(FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30)), owner_id="worker-a")
    other = WorkflowExecutionLease(execution.lease_manager, owner_id="worker-b")
    entered_event = Event()
    release_event = Event()
    entered = []

    def first():
        def action(_lease):
            entered.append("a")
            entered_event.set()
            release_event.wait(timeout=2)
            return "a"
        return LeaseGuardedExecutor(execution).execute("TASK-1", action)

    def second():
        assert entered_event.wait(timeout=2)
        with pytest.raises(LeaseUnavailable):
            LeaseGuardedExecutor(other).execute("TASK-1", lambda _lease: entered.append("b"))
        return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first)
        second_future = pool.submit(second)
        assert second_future.result() == "rejected"
        release_event.set()
        assert first_future.result() == "a"

    assert entered == ["a"]


def test_guarded_execution_releases_after_failure():
    manager = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    first = LeaseGuardedExecutor(WorkflowExecutionLease(manager, owner_id="worker-a"))
    second = LeaseGuardedExecutor(WorkflowExecutionLease(manager, owner_id="worker-b"))

    with pytest.raises(RuntimeError):
        first.execute("TASK-1", lambda _lease: (_ for _ in ()).throw(RuntimeError("boom")))

    assert second.execute("TASK-1", lambda _lease: "recovered") == "recovered"
