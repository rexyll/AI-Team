import threading

import pytest

from runtime.result_fencing import ResultCommitFencer
from runtime.task_lease_store import DurableTaskLeaseStore


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_current_owner_can_commit_result(tmp_path):
    clock = FakeClock()
    store = DurableTaskLeaseStore(tmp_path, clock=clock)
    store.acquire("TASK-001", "worker-a", "lease-a", 10)
    fencer = ResultCommitFencer(store)
    applied = []

    result = fencer.commit("TASK-001", "worker-a", "lease-a", lambda: applied.append("ok") or "result")

    assert result == "result"
    assert applied == ["ok"]


def test_late_worker_result_is_rejected_after_takeover(tmp_path):
    clock = FakeClock()
    store = DurableTaskLeaseStore(tmp_path, clock=clock)
    store.acquire("TASK-001", "worker-a", "lease-a", 10)
    clock.advance(10)
    store.acquire("TASK-001", "worker-b", "lease-b", 10)
    fencer = ResultCommitFencer(store)
    applied = []

    decision = fencer.validate("TASK-001", "worker-a", "lease-a")
    assert decision.accepted is False
    assert decision.reason == "Worker lease ownership mismatch"

    with pytest.raises(PermissionError):
        fencer.commit("TASK-001", "worker-a", "lease-a", lambda: applied.append("late"))

    assert applied == []


def test_result_commit_is_rejected_without_active_lease(tmp_path):
    fencer = ResultCommitFencer(DurableTaskLeaseStore(tmp_path))

    with pytest.raises(PermissionError, match="no active worker lease"):
        fencer.commit("TASK-001", "worker-a", "lease-a", lambda: "result")


def test_commit_holds_store_boundary_while_result_is_applied(tmp_path):
    clock = FakeClock()
    store = DurableTaskLeaseStore(tmp_path, clock=clock)
    store.acquire("TASK-001", "worker-a", "lease-a", 10)
    fencer = ResultCommitFencer(store)
    started = threading.Event()
    release_callback = threading.Event()
    commit_result = []
    takeover_result = []

    def apply_result():
        started.set()
        assert release_callback.wait(timeout=2)
        return "worker-a-result"

    def commit():
        commit_result.append(fencer.commit("TASK-001", "worker-a", "lease-a", apply_result))

    thread = threading.Thread(target=commit)
    thread.start()
    assert started.wait(timeout=2)

    clock.advance(10)
    takeover_thread = threading.Thread(
        target=lambda: takeover_result.append(
            store.acquire("TASK-001", "worker-b", "lease-b", 10)
        )
    )
    takeover_thread.start()

    release_callback.set()
    thread.join(timeout=2)
    takeover_thread.join(timeout=2)

    assert commit_result == ["worker-a-result"]
    assert takeover_result[0] is not None
    assert takeover_result[0].worker_id == "worker-b"
    assert store.owner("TASK-001").worker_id == "worker-b"
