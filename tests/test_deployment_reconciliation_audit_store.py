from __future__ import annotations

import json
import multiprocessing
import os

import pytest

from runtime.deployment_reconciliation_audit import _ZERO_DIGEST
from runtime.deployment_reconciliation_audit_store import (
    DurableReconciliationAuditStore,
    ReconciliationAuditHead,
    ReconciliationAuditIntegrityError,
)
from runtime.deployment_reconciliation_contract import AuthenticatedPrincipal


def _principal(subject: str = "operator-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject=subject,
        issuer="test-host-auth",
        authentication_method="test-signed-assertion",
        authenticated_at="2026-11-18T08:00:00Z",
    )


def _record(root: str, index: int) -> None:
    DurableReconciliationAuditStore(root).record(
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
        proposal_digest=f"{index:064x}",
        evidence_digest=f"{index + 1:064x}",
    )


def test_audit_store_appends_and_reloads_a_verified_hash_chain(tmp_path):
    store = DurableReconciliationAuditStore(tmp_path)
    first = store.record(
        action="reconciliation_proposed",
        actor=_principal(),
        approval_id="approval-1",
        operation_id="operation-1",
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
        recorded_at="2026-11-18T08:01:00Z",
    )
    second = store.record(
        action="reconciliation_approved",
        actor=_principal("operator-2"),
        approval_id="approval-1",
        operation_id="operation-1",
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
        recorded_at="2026-11-18T08:02:00Z",
    )

    reopened = DurableReconciliationAuditStore(tmp_path)
    events = reopened.events(operation_id="operation-1")
    assert [item.action for item in events] == [
        "reconciliation_proposed",
        "reconciliation_approved",
    ]
    assert events[0].previous_digest == _ZERO_DIGEST
    assert events[1].previous_digest == first.event_digest
    assert events[1].sequence == 2
    assert second.event_digest == reopened.verify().event_digest
    assert reopened.verify() == ReconciliationAuditHead(2, second.event_digest)
    assert reopened.verify(
        trusted_head=ReconciliationAuditHead(2, second.event_digest)
    ).sequence == 2


def test_audit_store_rejects_incorrect_external_trusted_head(tmp_path):
    store = DurableReconciliationAuditStore(tmp_path)
    empty = store.verify()
    assert empty == ReconciliationAuditHead(0, _ZERO_DIGEST)
    store.record(
        action="reconciliation_rejected",
        actor=_principal(),
        approval_id="approval-2",
        operation_id="operation-2",
        provider="docker-local",
        project="demo",
        environment="staging",
        journal_phase="needs_reconciliation",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
        proposal_digest="e" * 64,
        evidence_digest="f" * 64,
    )
    with pytest.raises(
        ReconciliationAuditIntegrityError,
        match="externally trusted checkpoint",
    ):
        store.verify(trusted_head=empty)


def test_audit_store_detects_event_payload_tampering(tmp_path):
    store = DurableReconciliationAuditStore(tmp_path)
    store.record(
        action="reconciliation_proposed",
        actor=_principal(),
        approval_id="approval-3",
        operation_id="operation-3",
        provider="docker-local",
        project="demo",
        environment="staging",
        journal_phase="needs_reconciliation",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
        proposal_digest="1" * 64,
        evidence_digest="2" * 64,
    )
    payload = json.loads(store.path.read_text(encoding="utf-8").splitlines()[0])
    payload["project"] = "tampered"
    store.path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ReconciliationAuditIntegrityError, match="event_digest"):
        store.events()


def test_audit_store_fails_closed_on_truncated_or_blank_tail(tmp_path):
    store = DurableReconciliationAuditStore(tmp_path)
    store.path.write_text("{\"partial\":", encoding="utf-8")
    with pytest.raises(ReconciliationAuditIntegrityError, match="line 1"):
        store.events()


def test_audit_store_rejects_prebuilt_event_that_does_not_extend_head(tmp_path):
    store = DurableReconciliationAuditStore(tmp_path)
    event = store._build_event(
        sequence=2,
        previous_digest="f" * 64,
        action="reconciliation_proposed",
        actor=_principal(),
        approval_id="approval-4",
        operation_id="operation-4",
        provider="docker-local",
        project="demo",
        environment="staging",
        journal_phase="needs_reconciliation",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
        proposal_digest="3" * 64,
        evidence_digest="4" * 64,
        recorded_at="2026-11-18T08:03:00Z",
    )
    with pytest.raises(ValueError, match="does not extend"):
        store.append(event)
    assert store.events() == ()


def test_audit_store_serializes_concurrent_process_appends(tmp_path):
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_record, args=(str(tmp_path), index))
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    events = DurableReconciliationAuditStore(tmp_path).events()
    assert len(events) == 4
    assert [event.sequence for event in events] == [1, 2, 3, 4]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission assertion")
def test_audit_store_restricts_private_host_files(tmp_path):
    store = DurableReconciliationAuditStore(tmp_path)
    store.record(
        action="reconciliation_proposed",
        actor=_principal(),
        approval_id="approval-5",
        operation_id="operation-5",
        provider="docker-local",
        project="demo",
        environment="staging",
        journal_phase="needs_reconciliation",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
        proposal_digest="5" * 64,
        evidence_digest="6" * 64,
    )
    assert store.root.stat().st_mode & 0o777 == 0o700
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.lock_path.stat().st_mode & 0o777 == 0o600


def test_audit_store_exposes_no_mutation_or_truncate_api(tmp_path):
    store = DurableReconciliationAuditStore(tmp_path)
    assert not hasattr(store, "delete")
    assert not hasattr(store, "truncate")
    assert not hasattr(store, "update")
