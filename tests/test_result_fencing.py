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
