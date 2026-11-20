from __future__ import annotations

from hashlib import sha256

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import sqlite3

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
        self.ledger_id = "test-audit-ledger"
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
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
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
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
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
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
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
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
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
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
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
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
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
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
    )

    with pytest.raises(ReconciliationAuditAnchorError):
        _record(store, 1)
    assert store.path.exists() is False


def test_anchored_store_covers_approval_claim_and_terminal_events(tmp_path):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
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


def test_anchored_store_serializes_concurrent_writers_across_instances(tmp_path):
    anchor = _MemoryHeadAnchor()
    root = tmp_path / "audit"
    stores = [
        ExternallyAnchoredReconciliationAuditStore(
            root, anchor=anchor, expected_ledger_id="test-audit-ledger"
        )
        for _ in range(4)
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        events = list(
            executor.map(
                lambda index: _record(stores[index], index + 1),
                range(4),
            )
        )

    assert sorted(event.sequence for event in events) == [1, 2, 3, 4]
    assert anchor.head.sequence == 4
    assert stores[0].verify() == anchor.head
    assert len(stores[0].events()) == 4


def test_anchored_events_reject_a_local_append_that_bypasses_the_wrapper(tmp_path):
    anchor = _MemoryHeadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit", anchor=anchor,
        expected_ledger_id="test-audit-ledger",
    )
    first = _record(store, 1)
    assert store.events() == (first,)

    # Simulate an accidental direct use of the base store API. The appended
    # event is durable locally but was not checkpointed by the external anchor.
    bypassed = DurableReconciliationAuditStore.record(
        store,
        action="reconciliation_proposed",
        actor=_principal("bypass"),
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
    assert bypassed.sequence == 2
    assert anchor.head.sequence == 1

    with pytest.raises(ReconciliationAuditAnchorError):
        store.events()


def test_external_anchor_requires_exact_stable_ledger_identity(tmp_path):
    anchor = _MemoryHeadAnchor()

    with pytest.raises(
        ReconciliationAuditAnchorError, match="identity does not match"
    ):
        ExternallyAnchoredReconciliationAuditStore(
            tmp_path / "wrong",
            anchor=anchor,
            expected_ledger_id="production/ledger-a",
        )

    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "correct",
        anchor=anchor,
        expected_ledger_id="test-audit-ledger",
    )
    anchor.ledger_id = "test-audit-ledger-other"
    with pytest.raises(ReconciliationAuditAnchorError, match="identity changed"):
        store.verify()


class _SQLiteProcessHeadAnchor:
    """Test-only cross-process CAS anchor stored outside the audit directory."""

    ledger_id = "process-test-audit-ledger"

    def __init__(self, database_path, *, provision=False):
        self.database_path = str(database_path)
        if provision:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS audit_head "
                    "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                    "sequence INTEGER NOT NULL, event_digest TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO audit_head "
                    "(singleton, sequence, event_digest) VALUES (1, 0, ?)",
                    (_ZERO_DIGEST,),
                )
                connection.commit()

    def read_head(self):
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            row = connection.execute(
                "SELECT sequence, event_digest FROM audit_head WHERE singleton=1"
            ).fetchone()
        if row is None:
            raise RuntimeError("test external anchor was not provisioned")
        return ReconciliationAuditHead(row[0], row[1])

    def compare_and_set(self, expected, replacement):
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT sequence, event_digest FROM audit_head WHERE singleton=1"
            ).fetchone()
            if row != (expected.sequence, expected.event_digest):
                connection.rollback()
                return False
            cursor = connection.execute(
                "UPDATE audit_head SET sequence=?, event_digest=? "
                "WHERE singleton=1 AND sequence=? AND event_digest=?",
                (
                    replacement.sequence,
                    replacement.event_digest,
                    expected.sequence,
                    expected.event_digest,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            connection.commit()
            return True


def _append_anchored_event_from_process(root, database_path, index, queue):
    try:
        anchor = _SQLiteProcessHeadAnchor(database_path)
        store = ExternallyAnchoredReconciliationAuditStore(
            root,
            anchor=anchor,
            expected_ledger_id=anchor.ledger_id,
        )
        event = _record(store, index)
        queue.put(("success", event.sequence))
    except Exception as exc:
        queue.put(("error", type(exc).__name__, str(exc)))


def test_anchored_store_serializes_spawned_process_writers_and_remote_cas(tmp_path):
    context = multiprocessing.get_context("spawn")
    audit_root = tmp_path / "shared-audit"
    anchor_db = tmp_path / "external-anchor" / "checkpoint.sqlite"
    anchor_db.parent.mkdir(parents=True)
    anchor = _SQLiteProcessHeadAnchor(anchor_db, provision=True)

    queue = context.Queue()
    processes = [
        context.Process(
            target=_append_anchored_event_from_process,
            args=(str(audit_root), str(anchor_db), index, queue),
        )
        for index in range(1, 5)
    ]
    for process in processes:
        process.start()

    outcomes = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    assert [item[0] for item in outcomes] == ["success"] * 4
    assert sorted(item[1] for item in outcomes) == [1, 2, 3, 4]

    reopened = ExternallyAnchoredReconciliationAuditStore(
        audit_root,
        anchor=anchor,
        expected_ledger_id=anchor.ledger_id,
    )
    events = reopened.events()
    assert [item.sequence for item in events] == [1, 2, 3, 4]
    assert reopened.verify() == anchor.read_head()
