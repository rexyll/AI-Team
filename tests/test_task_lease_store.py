from runtime.task_lease_store import DurableTaskLeaseStore


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_durable_lease_survives_new_store_instance(tmp_path):
    clock = FakeClock()
    first = DurableTaskLeaseStore(tmp_path, clock=clock)
    lease = first.acquire("TASK-001", "worker-a", "lease-a", 10)

    second = DurableTaskLeaseStore(tmp_path, clock=clock)

    assert second.owner("TASK-001") == lease
    assert second.acquire("TASK-001", "worker-b", "lease-b", 10) is None


def test_expired_durable_lease_can_be_taken_over(tmp_path):
    clock = FakeClock()
    store = DurableTaskLeaseStore(tmp_path, clock=clock)
    first = store.acquire("TASK-001", "worker-a", "lease-a", 10)
    clock.advance(10)

    second = store.acquire("TASK-001", "worker-b", "lease-b", 10)

    assert second is not None
    assert second != first
    assert store.owner("TASK-001") == second


def test_stale_worker_cannot_mutate_durable_recovered_lease(tmp_path):
    clock = FakeClock()
    store = DurableTaskLeaseStore(tmp_path, clock=clock)
    store.acquire("TASK-001", "worker-a", "lease-a", 10)
    clock.advance(10)
    store.acquire("TASK-001", "worker-b", "lease-b", 10)

    assert store.renew("TASK-001", "worker-a", "lease-a", 10) is None
    assert store.release("TASK-001", "worker-a", "lease-a") is False
    assert store.owner("TASK-001").worker_id == "worker-b"


def test_release_is_idempotent_across_store_instances(tmp_path):
    first = DurableTaskLeaseStore(tmp_path)
    first.acquire("TASK-001", "worker-a", "lease-a", 10)
    second = DurableTaskLeaseStore(tmp_path)

    assert second.release("TASK-001", "worker-a", "lease-a") is True
    assert first.release("TASK-001", "worker-a", "lease-a") is False
