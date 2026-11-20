from __future__ import annotations

from hashlib import sha256

import pytest

from runtime.deployment_reconciliation_anchored_audit_store import (
    ExternallyAnchoredReconciliationAuditStore,
    ReconciliationAuditAnchorConflict,
    ReconciliationAuditAnchorError,
)
from runtime.deployment_reconciliation_audit_store import (
    DurableReconciliationAuditStore,
    ReconciliationAuditHead,
    _ZERO_DIGEST,
)
from runtime.deployment_reconciliation_contract import AuthenticatedPrincipal


class _MemoryHeadAnchor:
    """Test-only atomic anchor; production must use an external durable service."""

    def __init__(self, head=None):
        self.head = head or ReconciliationAuditHead(0, _ZERO_DIGEST)
        self.fail_next_cas = False
        self.raise_after_commit = False

    def read_head(self):
        return self.head

    def compare_and_set(self, expected, replacement):
        if self.fail_next_cas:
            self.fail_next_cas = False
            return False
        if self.head != expected:
            return False
        self.head = replacement
        if self.raise_after_commit:
            self.raise_after_commit = False
            raise OSError("simulated lost acknowledgement after anchor commit")
        return True


def _principal(subject="operator-1"):
    return AuthenticatedPrincipal(
        subject=subject,
        issuer="test-host-auth",
        authentication_method="test-signed-assertion",
        authenticated_at="2026-11-20T10:00:00Z",
    )


def _record(store, index):
    return store.record(
        action="reconciliation_proposed",
        actor=_principal(f"operator-{index}"),
        approval_id=f"approval-{index}",
        operation_id=f"operation-{index}",
        provider="docker-local",
        project="demo",
        environment="staging",
        journal_phase="needs_reconciliation",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
        proposal_digest=sha256(f"proposal-{index}".encode()).hexdigest(),
        evidence_digest=sha256(f"evidence-{index}".encode()).hexdigest(),
    )


def test_anchored_store_advances_external_head_after_each_durable_append(tmp_path):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )

    first = _record(store, 1)
    assert anchor.head == ReconciliationAuditHead(1, first.event_digest)
    assert store.verify() == anchor.head
    assert store.events() == (first,)

    second = _record(store, 2)
    assert anchor.head == ReconciliationAuditHead(2, second.event_digest)
    assert store.verify() == anchor.head
    assert [event.sequence for event in store.events()] == [1, 2]


def test_anchored_store_fails_closed_when_local_chain_is_tampered(tmp_path):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )
    _record(store, 1)

    store.path.write_text(
        store.path.read_text(encoding="utf-8").replace("demo", "evil"),
        encoding="utf-8",
    )
    with pytest.raises(ReconciliationAuditAnchorError):
        store.events()
    with pytest.raises(ReconciliationAuditAnchorError):
        _record(store, 2)


def test_anchored_store_rejects_preexisting_unanchored_local_events(tmp_path):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )

    # Simulate a writer that bypasses the anchored wrapper.
    common = dict(
        actor=_principal("operator-bypass"),
        approval_id="approval-bypass",
        operation_id="operation-bypass",
        provider="docker-local",
        project="demo",
        environment="staging",
        journal_phase="needs_reconciliation",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
        proposal_digest="c" * 64,
        evidence_digest="d" * 64,
    )
    unanchored = DurableReconciliationAuditStore.record(
        store, action="reconciliation_proposed", **common
    )
    assert unanchored.sequence == 1
    assert anchor.head == ReconciliationAuditHead(0, _ZERO_DIGEST)

    second = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )
    # A different external genesis checkpoint must not silently adopt the local chain.
    with pytest.raises(ReconciliationAuditAnchorError):
        second.verify()
    with pytest.raises(ReconciliationAuditAnchorError):
        _record(second, 2)


def test_anchor_cas_conflict_leaves_local_ledger_ahead_and_blocks_future_writes(
    tmp_path,
):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )
    anchor.fail_next_cas = True

    with pytest.raises(ReconciliationAuditAnchorConflict):
        _record(store, 1)

    # The append is not rolled back or silently re-anchored.
    assert anchor.head == ReconciliationAuditHead(0, _ZERO_DIGEST)
    with pytest.raises(ReconciliationAuditAnchorError):
        store.verify()
    with pytest.raises(ReconciliationAuditAnchorError):
        _record(store, 2)


def test_lost_cas_acknowledgement_is_resolved_by_rereading_external_head(tmp_path):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )
    anchor.raise_after_commit = True

    event = _record(store, 1)

    assert anchor.head == ReconciliationAuditHead(1, event.event_digest)
    assert store.verify() == anchor.head
    assert store.events() == (event,)


def test_anchored_store_requires_the_external_genesis_checkpoint(tmp_path):
    wrong = ReconciliationAuditHead(1, "f" * 64)
    anchor = _MemoryHeadAnchor(wrong)
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )

    with pytest.raises(ReconciliationAuditAnchorError):
        _record(store, 1)
    assert store.path.exists() is False


def test_anchored_store_covers_approval_claim_and_terminal_events(tmp_path):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor
    )
    requester = _principal("requester")
    approver = _principal("approver")
    common = dict(
        approval_id="approval-anchored",
        operation_id="operation-anchored",
        provider="docker-local",
        project="demo",
        environment="staging",
        journal_phase="needs_reconciliation",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
        proposal_digest="c" * 64,
        evidence_digest="d" * 64,
    )
    token_digest = sha256(b"anchored-one-use-token").hexdigest()
    store.record(
        action="reconciliation_proposed", actor=requester, **common
    )
    approved = store.record(
        action="reconciliation_approved",
        actor=approver,
        **common,
        approval_token_digest=token_digest,
        approval_expires_at="2030-01-01T00:00:00Z",
    )
    assert anchor.head == ReconciliationAuditHead(2, approved.event_digest)

    started = store.begin_approval_consumption(
        approval_id="approval-anchored",
        token_digest=token_digest,
        proposal_digest="c" * 64,
        evidence_digest="d" * 64,
        approval_expires_at="2030-01-01T00:00:00Z",
        requester=requester,
        approver=approver,
    )
    assert anchor.head == ReconciliationAuditHead(3, started.event_digest)

    finished = store.finish_approval_consumption(
        approval_id="approval-anchored",
        proposal_digest="c" * 64,
        evidence_digest="d" * 64,
        action="reconciliation_approval_consumed",
    )
    assert anchor.head == ReconciliationAuditHead(4, finished.event_digest)
    assert [item.sequence for item in store.events()] == [1, 2, 3, 4]
