from runtime.delivery_audit import DurableDeliveryAuditStore
from runtime.delivery_store import DurableDeliveryStore


def test_delivery_store_audits_begin_complete_and_duplicate(tmp_path):
    audit = DurableDeliveryAuditStore(tmp_path / "audit")
    store = DurableDeliveryStore(tmp_path / "delivery", audit_store=audit)

    assert store.commit("delivery-001", lambda: "ok") == "ok"
    assert store.commit("delivery-001", lambda: "replayed") is None

    assert [event.action for event in audit.records("delivery-001")] == [
        "begin",
        "complete",
        "duplicate",
    ]


def test_delivery_store_audits_recovery_decisions(tmp_path):
    audit = DurableDeliveryAuditStore(tmp_path / "audit")
    store = DurableDeliveryStore(tmp_path / "delivery", audit_store=audit)

    store.begin("delivery-commit")
    store.recover_processing("delivery-commit", "commit")
    store.begin("delivery-retry")
    store.recover_processing("delivery-retry", "retry")

    commit_events = audit.records("delivery-commit")
    retry_events = audit.records("delivery-retry")
    assert commit_events[-1].action == "recover_commit"
    assert retry_events[-1].action == "recover_retry"
    assert commit_events[-1].status_after == "committed"
    assert retry_events[-1].status_after is None


def test_auditing_is_opt_in_and_does_not_change_default_behavior(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    assert store.commit("delivery-001", lambda: 42) == 42
    assert store.status("delivery-001").status == "committed"
