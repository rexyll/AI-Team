from runtime.delivery_store import DurableDeliveryStore
from runtime.result_fencing import ResultCommitFencer
from runtime.task_lease_store import DurableTaskLeaseStore


def test_delivery_key_is_stable_and_task_scoped():
    key_a = ResultCommitFencer.delivery_key("TASK-001", 1, "delivery-1")
    key_a_again = ResultCommitFencer.delivery_key("TASK-001", 1, "delivery-1")
    key_b = ResultCommitFencer.delivery_key("TASK-002", 1, "delivery-1")

    assert key_a == key_a_again
    assert key_a != key_b


def test_fenced_duplicate_delivery_is_applied_only_once(tmp_path):
    lease_store = DurableTaskLeaseStore(tmp_path / "leases")
    delivery_store = DurableDeliveryStore(tmp_path / "deliveries")
    lease_store.acquire("TASK-001", "worker-a", "lease-a", 10)
    fencer = ResultCommitFencer(lease_store, delivery_store)
    applied = []

    first = fencer.commit(
        "TASK-001", "worker-a", "lease-a", lambda: applied.append("once") or "ok",
        attempt=1, delivery_id="delivery-1",
    )
    second = fencer.commit(
        "TASK-001", "worker-a", "lease-a", lambda: applied.append("twice") or "bad",
        attempt=1, delivery_id="delivery-1",
    )

    assert first == "ok"
    assert second is None
    assert applied == ["once"]


def test_same_delivery_id_on_different_attempt_is_distinct(tmp_path):
    lease_store = DurableTaskLeaseStore(tmp_path / "leases")
    delivery_store = DurableDeliveryStore(tmp_path / "deliveries")
    lease_store.acquire("TASK-001", "worker-a", "lease-a", 10)
    fencer = ResultCommitFencer(lease_store, delivery_store)
    applied = []

    fencer.commit("TASK-001", "worker-a", "lease-a", lambda: applied.append(1), attempt=1, delivery_id="same")
    fencer.commit("TASK-001", "worker-a", "lease-a", lambda: applied.append(2), attempt=2, delivery_id="same")

    assert applied == [1, 2]
