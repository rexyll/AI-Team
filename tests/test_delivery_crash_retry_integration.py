from __future__ import annotations

import multiprocessing
from pathlib import Path

from runtime.delivery_audit import DurableDeliveryAuditStore
from runtime.delivery_reconciliation import (
    AuthoritativeDeliveryReconciler,
    SinkMutationState,
    SinkReconciliation,
)
from runtime.delivery_store import DurableDeliveryStore


def _crash_after_apply(root: str, key: str, ready) -> None:
    audit = DurableDeliveryAuditStore(Path(root) / "audit")
    store = DurableDeliveryStore(Path(root) / "delivery", audit_store=audit)
    decision = store.begin(key)
    assert decision.accepted
    ready.put("reserved")
    # Simulate an external mutation that completed, followed by worker death
    # before the durable delivery marker could be completed.
    ready.put("external-applied")
    raise SystemExit(17)


class _Sink:
    def __init__(self, state: SinkMutationState):
        self.state = state

    def reconcile(self, delivery_key: str) -> SinkReconciliation:
        return SinkReconciliation(delivery_key, self.state)


def test_cross_process_crash_after_apply_reconciles_to_commit(tmp_path):
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    key = "delivery-crash-001"
    worker = context.Process(target=_crash_after_apply, args=(str(tmp_path), key, events))
    worker.start()
    assert events.get(timeout=5) == "reserved"
    assert events.get(timeout=5) == "external-applied"
    worker.join(timeout=5)
    assert worker.exitcode == 17

    audit = DurableDeliveryAuditStore(tmp_path / "audit")
    store = DurableDeliveryStore(tmp_path / "delivery", audit_store=audit)
    assert store.status(key).status == "processing"

    decision = AuthoritativeDeliveryReconciler(
        store, _Sink(SinkMutationState.APPLIED)
    ).reconcile(key)

    assert decision.status == "committed"
    assert store.status(key).status == "committed"
    actions = [event.action for event in audit.records(key)]
    assert actions == ["begin", "recover_commit"]


def test_cross_process_crash_before_apply_releases_for_retry(tmp_path):
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    key = "delivery-crash-002"
    worker = context.Process(target=_crash_after_apply, args=(str(tmp_path), key, events))
    worker.start()
    assert events.get(timeout=5) == "reserved"
    # The worker dies before any external mutation in this scenario.
    worker.terminate()
    worker.join(timeout=5)

    audit = DurableDeliveryAuditStore(tmp_path / "audit")
    store = DurableDeliveryStore(tmp_path / "delivery", audit_store=audit)
    assert store.status(key).status == "processing"

    decision = AuthoritativeDeliveryReconciler(
        store, _Sink(SinkMutationState.NOT_APPLIED)
    ).reconcile(key)

    assert decision.status is None
    assert store.status(key) is None
    actions = [event.action for event in audit.records(key)]
    assert actions == ["begin", "recover_retry"]


def test_cross_process_unknown_state_preserves_processing_marker(tmp_path):
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    key = "delivery-crash-003"
    worker = context.Process(target=_crash_after_apply, args=(str(tmp_path), key, events))
    worker.start()
    assert events.get(timeout=5) == "reserved"
    worker.terminate()
    worker.join(timeout=5)

    audit = DurableDeliveryAuditStore(tmp_path / "audit")
    store = DurableDeliveryStore(tmp_path / "delivery", audit_store=audit)
    assert store.status(key).status == "processing"

    from runtime.delivery_reconciliation import ReconciliationRequired

    try:
        AuthoritativeDeliveryReconciler(
            store, _Sink(SinkMutationState.UNKNOWN), audit_store=audit
        ).reconcile(key)
    except ReconciliationRequired:
        pass
    else:
        raise AssertionError("UNKNOWN sink state must require reconciliation")

    assert store.status(key).status == "processing"
    assert audit.records(key)[-1].action == "reconciliation_required"
