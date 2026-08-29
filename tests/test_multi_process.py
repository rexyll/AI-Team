from runtime.multi_process import TaskLeaseCoordinator


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_only_one_worker_can_own_task_lease():
    clock = FakeClock()
    coordinator = TaskLeaseCoordinator(clock=clock)

    first = coordinator.acquire("TASK-001", "worker-a", "lease-a", 10)
    second = coordinator.acquire("TASK-001", "worker-b", "lease-b", 10)

    assert first is not None
    assert second is None
    assert coordinator.owner("TASK-001") == first


def test_lease_expires_and_another_worker_can_recover_task():
    clock = FakeClock()
    coordinator = TaskLeaseCoordinator(clock=clock)
    first = coordinator.acquire("TASK-001", "worker-a", "lease-a", 10)
    clock.advance(10)

    second = coordinator.acquire("TASK-001", "worker-b", "lease-b", 10)

    assert second is not None
    assert second.worker_id == "worker-b"
    assert coordinator.owner("TASK-001") == second
    assert first != second


def test_stale_worker_cannot_renew_or_release_recovered_lease():
    clock = FakeClock()
    coordinator = TaskLeaseCoordinator(clock=clock)
    coordinator.acquire("TASK-001", "worker-a", "lease-a", 10)
    clock.advance(11)
    coordinator.acquire("TASK-001", "worker-b", "lease-b", 10)

    assert coordinator.renew("TASK-001", "worker-a", "lease-a", 10) is None
    assert coordinator.release("TASK-001", "worker-a", "lease-a") is False
    assert coordinator.owner("TASK-001").worker_id == "worker-b"


def test_release_is_idempotent_for_same_lease():
    coordinator = TaskLeaseCoordinator()
    coordinator.acquire("TASK-001", "worker-a", "lease-a", 10)

    assert coordinator.release("TASK-001", "worker-a", "lease-a") is True
    assert coordinator.release("TASK-001", "worker-a", "lease-a") is False
    assert coordinator.owner("TASK-001") is None
