import multiprocessing
import os

from runtime.delivery_store import DurableDeliveryStore


def _crash_after_apply(root, key, marker):
    store = DurableDeliveryStore(root)

    def apply():
        open(marker, "w", encoding="utf-8").write("applied")
        os._exit(17)

    store.commit(key, apply)


def test_crash_after_apply_before_ack_leaves_processing(tmp_path):
    marker = tmp_path / "applied.txt"
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_after_apply,
        args=(str(tmp_path / "deliveries"), "delivery-crash", str(marker)),
    )
    process.start()
    process.join(timeout=5)

    assert process.exitcode == 17
    assert marker.read_text(encoding="utf-8") == "applied"

    store = DurableDeliveryStore(tmp_path / "deliveries")
    assert store.status("delivery-crash").status == "processing"
    assert store.begin("delivery-crash").duplicate is True


def test_processing_can_be_reconciled_as_committed_without_replaying_callback(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    store.begin("delivery-001")
    applied = []

    decision = store.recover_processing("delivery-001", "commit")

    assert decision.accepted is True
    assert decision.status == "committed"
    assert store.status("delivery-001").status == "committed"
    assert store.commit("delivery-001", lambda: applied.append("replayed")) is None
    assert applied == []


def test_processing_can_be_released_for_retry_only_after_reconciliation(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    store.begin("delivery-001")

    decision = store.recover_processing("delivery-001", "retry")

    assert decision.accepted is True
    assert decision.status is None
    assert store.status("delivery-001") is None
    assert store.commit("delivery-001", lambda: "retry-result") == "retry-result"
    assert store.status("delivery-001").status == "committed"
