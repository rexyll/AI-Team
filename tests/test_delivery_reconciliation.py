import pytest

from runtime.delivery_reconciliation import (
    AuthoritativeDeliveryReconciler,
    ReconciliationRequired,
    SinkMutationState,
    SinkReconciliation,
)
from runtime.delivery_store import DurableDeliveryStore


class _Sink:
    def __init__(self, state):
        self.state = state

    def reconcile(self, delivery_key):
        return SinkReconciliation(delivery_key, self.state)


def test_applied_sink_state_commits_without_replaying_delivery(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    store.begin("delivery-001")

    decision = AuthoritativeDeliveryReconciler(
        store, _Sink(SinkMutationState.APPLIED)
    ).reconcile("delivery-001")

    assert decision.status == "committed"
    assert store.status("delivery-001").status == "committed"


def test_not_applied_sink_state_releases_delivery_for_retry(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    store.begin("delivery-001")

    decision = AuthoritativeDeliveryReconciler(
        store, _Sink(SinkMutationState.NOT_APPLIED)
    ).reconcile("delivery-001")

    assert decision.status is None
    assert store.status("delivery-001") is None


def test_unknown_sink_state_never_guesses_or_replays(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    store.begin("delivery-001")

    with pytest.raises(ReconciliationRequired):
        AuthoritativeDeliveryReconciler(
            store, _Sink(SinkMutationState.UNKNOWN)
        ).reconcile("delivery-001")

    assert store.status("delivery-001").status == "processing"


def test_reconciliation_rejects_mismatched_delivery_identity(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    store.begin("delivery-001")

    class _WrongSink:
        def reconcile(self, delivery_key):
            return SinkReconciliation("delivery-other", SinkMutationState.APPLIED)

    with pytest.raises(ValueError, match="delivery key mismatch"):
        AuthoritativeDeliveryReconciler(store, _WrongSink()).reconcile("delivery-001")
