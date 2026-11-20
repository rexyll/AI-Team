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
    inspection = store.inspect_anchor_state()
    assert inspection.status == "local_ahead"
    assert inspection.local_head is not None
    assert inspection.local_head.sequence == 1
    assert inspection.external_head == anchor.head
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
    assert store.inspect_anchor_state().status == "identity_mismatch"
    with pytest.raises(ReconciliationAuditAnchorError, match="identity changed"):
        store.verify()


class _SQLiteProcessHeadAnchor:
    """Test-only namespaced cross-process CAS anchor stored outside the audit directory."""

    DEFAULT_LEDGER_ID = "process-test-audit-ledger"

    def __init__(
        self,
        database_path,
        *,
        ledger_id=DEFAULT_LEDGER_ID,
        provision=False,
    ):
        if not isinstance(ledger_id, str) or not ledger_id.strip():
            raise ValueError("test ledger_id must be a non-empty string")
        self.database_path = str(database_path)
        self.ledger_id = ledger_id
        if provision:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS audit_head "
                    "(ledger_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, "
                    "event_digest TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO audit_head "
                    "(ledger_id, sequence, event_digest) VALUES (?, 0, ?)",
                    (self.ledger_id, _ZERO_DIGEST),
                )
                connection.commit()

    def read_head(self):
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            row = connection.execute(
                "SELECT sequence, event_digest FROM audit_head WHERE ledger_id=?",
                (self.ledger_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("test external anchor was not provisioned")
        return ReconciliationAuditHead(row[0], row[1])

    def compare_and_set(self, expected, replacement):
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT sequence, event_digest FROM audit_head WHERE ledger_id=?",
                (self.ledger_id,),
            ).fetchone()
            if row != (expected.sequence, expected.event_digest):
                connection.rollback()
                return False
            cursor = connection.execute(
                "UPDATE audit_head SET sequence=?, event_digest=? "
                "WHERE ledger_id=? AND sequence=? AND event_digest=?",
                (
                    replacement.sequence,
                    replacement.event_digest,
                    self.ledger_id,
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


def test_anchor_inspection_reports_anchored_and_local_behind_states(tmp_path):
    anchored = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "anchored",
        anchor=_MemoryHeadAnchor(),
        expected_ledger_id="test-audit-ledger",
    )
    assert anchored.inspect_anchor_state().status == "anchored"

    external = ReconciliationAuditHead(2, "f" * 64)
    behind = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "behind",
        anchor=_MemoryHeadAnchor(external),
        expected_ledger_id="test-audit-ledger",
    )
    inspection = behind.inspect_anchor_state()
    assert inspection.status == "local_behind"
    assert inspection.local_head == ReconciliationAuditHead(0, _ZERO_DIGEST)
    assert inspection.external_head == external


def test_anchor_inspection_reports_same_sequence_fork_and_invalid_local_chain(
    tmp_path,
):
    fork_anchor = _MemoryHeadAnchor(ReconciliationAuditHead(1, "f" * 64))
    forked = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "forked",
        anchor=fork_anchor,
        expected_ledger_id="test-audit-ledger",
    )
    common = dict(
        actor=_principal("fork-writer"),
        approval_id="approval-fork",
        operation_id="operation-fork",
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
    DurableReconciliationAuditStore.record(
        forked, action="reconciliation_proposed", **common
    )
    fork_inspection = forked.inspect_anchor_state()
    assert fork_inspection.status == "forked"
    assert fork_inspection.local_head.sequence == 1
    assert fork_inspection.external_head == fork_anchor.head

    invalid_anchor = _MemoryHeadAnchor()
    invalid = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "invalid",
        anchor=invalid_anchor,
        expected_ledger_id="test-audit-ledger",
    )
    invalid.path.write_text('{"truncated":', encoding="utf-8")
    invalid_inspection = invalid.inspect_anchor_state()
    assert invalid_inspection.status == "local_invalid"
    assert invalid_inspection.local_head is None
    assert invalid_inspection.local_error is not None


def test_anchor_identity_drift_during_read_fails_closed(tmp_path):
    class _DriftingReadAnchor(_MemoryHeadAnchor):
        def read_head(self):
            head = super().read_head()
            self.ledger_id = "other-ledger-during-read"
            return head

    from runtime.deployment_reconciliation_anchored_audit_store import (
        ReconciliationAuditAnchorIdentityError,
    )

    anchor = _DriftingReadAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "read-drift",
        anchor=anchor,
        expected_ledger_id="test-audit-ledger",
    )

    with pytest.raises(ReconciliationAuditAnchorIdentityError):
        store.verify()
    assert store.inspect_anchor_state().status == "identity_mismatch"


def test_anchor_identity_drift_during_cas_fails_closed_after_local_append(tmp_path):
    class _DriftingCasAnchor(_MemoryHeadAnchor):
        def compare_and_set(self, expected, replacement):
            result = super().compare_and_set(expected, replacement)
            self.ledger_id = "other-ledger-during-cas"
            return result

    from runtime.deployment_reconciliation_anchored_audit_store import (
        ReconciliationAuditAnchorIdentityError,
    )

    anchor = _DriftingCasAnchor()
    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "cas-drift",
        anchor=anchor,
        expected_ledger_id="test-audit-ledger",
    )

    with pytest.raises(ReconciliationAuditAnchorIdentityError):
        _record(store, 1)

    # Local append and remote side effect are not rewritten or re-anchored.
    # The changed namespace makes the store permanently fail closed until an
    # operator establishes which external ledger was actually touched.
    inspection = store.inspect_anchor_state()
    assert inspection.status == "identity_mismatch"
    assert inspection.local_head == anchor.head
    assert inspection.local_head.sequence == 1


def test_anchor_inspection_reports_external_anchor_unavailable(tmp_path):
    class _UnavailableAnchor:
        ledger_id = "test-audit-ledger"

        def read_head(self):
            raise OSError("external anchor unavailable")

        def compare_and_set(self, expected, replacement):
            raise AssertionError("CAS must not be called during inspection")

    store = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit",
        anchor=_UnavailableAnchor(),
        expected_ledger_id="test-audit-ledger",
    )
    inspection = store.inspect_anchor_state()
    assert inspection.status == "anchor_unavailable"
    assert inspection.local_head == ReconciliationAuditHead(0, _ZERO_DIGEST)
    assert inspection.anchor_error == "ReconciliationAuditAnchorError"


def test_sqlite_anchor_checkpoint_survives_client_recreation_and_rejects_stale_cas(
    tmp_path,
):
    database = tmp_path / "external" / "checkpoint.sqlite"
    database.parent.mkdir(parents=True)
    first_client = _SQLiteProcessHeadAnchor(database, provision=True)
    genesis = first_client.read_head()
    committed = ReconciliationAuditHead(1, "a" * 64)

    assert first_client.compare_and_set(genesis, committed)

    reopened_client = _SQLiteProcessHeadAnchor(database)
    assert reopened_client.read_head() == committed
    assert not reopened_client.compare_and_set(
        genesis, ReconciliationAuditHead(1, "b" * 64)
    )
    assert reopened_client.read_head() == committed


def test_sqlite_anchor_namespaces_are_isolated_by_ledger_id(tmp_path):
    database = tmp_path / "external" / "checkpoint.sqlite"
    database.parent.mkdir(parents=True)
    ledger_a = _SQLiteProcessHeadAnchor(
        database, ledger_id="tenant-a/production", provision=True
    )
    ledger_b = _SQLiteProcessHeadAnchor(
        database, ledger_id="tenant-b/production", provision=True
    )
    genesis_a = ledger_a.read_head()
    genesis_b = ledger_b.read_head()
    advanced_a = ReconciliationAuditHead(1, "a" * 64)

    assert ledger_a.compare_and_set(genesis_a, advanced_a)
    assert ledger_a.read_head() == advanced_a
    assert ledger_b.read_head() == genesis_b

    store_b = ExternallyAnchoredReconciliationAuditStore(
        tmp_path / "audit-b",
        anchor=ledger_b,
        expected_ledger_id="tenant-b/production",
    )
    assert store_b.verify() == genesis_b
    assert store_b.inspect_anchor_state().status == "anchored"


def test_sqlite_anchor_cas_is_linearizable_across_independent_clients(tmp_path):
    database = tmp_path / "external" / "checkpoint.sqlite"
    database.parent.mkdir(parents=True)
    provisioner = _SQLiteProcessHeadAnchor(database, provision=True)
    expected = provisioner.read_head()
    clients = [_SQLiteProcessHeadAnchor(database) for _ in range(2)]
    replacements = [
        ReconciliationAuditHead(1, "a" * 64),
        ReconciliationAuditHead(1, "b" * 64),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda pair: pair[0].compare_and_set(expected, pair[1]),
                zip(clients, replacements),
            )
        )

    assert sorted(outcomes) == [False, True]
    assert provisioner.read_head() in replacements
