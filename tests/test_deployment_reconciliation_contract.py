from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.deployment_reconciliation_contract import (
    AuthenticatedPrincipal,
    ReconciliationApproval,
    ReconciliationEvidence,
    ReconciliationProposal,
    ReconciliationSnapshotReadReceipt,
    reconciliation_evidence_digest,
)
from runtime.deployment_replacement import ReplacementJournalRecord


def principal(subject):
    return AuthenticatedPrincipal(
        subject=subject,
        issuer="https://identity.example.test",
        authentication_method="webauthn",
        authenticated_at="2026-11-15T10:00:00Z",
    )


def journal(**overrides):
    values = dict(
        operation_id="replace-001",
        provider="docker-local",
        project="demo",
        environment="staging",
        target_deployment_id="release-new",
        previous_deployment_id="release-current",
        phase="needs_reconciliation",
        created_at="2026-11-15T09:00:00Z",
        updated_at="2026-11-15T09:10:00Z",
        candidate_runtime_id="runtime-candidate-immutable",
        previous_runtime_id="runtime-previous-immutable",
    )
    values.update(overrides)
    return ReplacementJournalRecord(**values)


def approval(operation="abort_candidate", **overrides):
    values = dict(
        approval_id="approval-001",
        operation=operation,
        provider="docker-local",
        project="demo",
        environment="staging",
        operation_id="replace-001",
        expected_phase="needs_reconciliation",
        target_deployment_id="release-new",
        previous_deployment_id="release-current",
        candidate_runtime_id="runtime-candidate-immutable",
        previous_runtime_id="runtime-previous-immutable",
        requested_by=principal("operator:requester"),
        approved_by=principal("operator:approver"),
        issued_at="2026-11-15T10:00:00Z",
        expires_at="2026-11-15T10:05:00Z",
    )
    values.update(overrides)
    return ReconciliationApproval(**values)


def evidence(kind, index, **overrides):
    values = dict(
        evidence_id=f"evidence-{index}",
        kind=kind,
        source="provider-observation",
        observed_at="2026-11-15T10:01:00Z",
        digest_sha256=f"{index:064x}",
    )
    values.update(overrides)
    return ReconciliationEvidence(**values)


def proposal(operation="abort_candidate", **overrides):
    record = overrides.pop("record", journal())
    auth = overrides.pop("approval", approval(operation))
    if operation == "abort_candidate":
        items = (
            evidence("provider_operation_inspection", 1),
            evidence("candidate_absence", 2, subject_runtime_id=record.candidate_runtime_id),
            evidence("previous_runtime_inspection", 3, subject_runtime_id=record.previous_runtime_id),
            evidence("previous_route_readback", 4, observed_runtime_id=record.previous_runtime_id),
        )
    else:
        items = (
            evidence("provider_operation_inspection", 1),
            evidence("candidate_route_readback", 2, observed_runtime_id=record.candidate_runtime_id),
            evidence("candidate_health", 3, subject_runtime_id=record.candidate_runtime_id),
            evidence("previous_runtime_retirement", 4, subject_runtime_id=record.previous_runtime_id),
        )
    values = dict(
        record=record,
        approval=auth,
        evidence=items,
        proposed_at="2026-11-15T10:02:00Z",
    )
    values.update(overrides)
    return ReconciliationProposal(**values)



def snapshot_receipt(record, evidence, **overrides):
    values = dict(
        reader_id="host-journal-reader-v1",
        snapshot_id="snapshot-001",
        record=record,
        evidence=evidence,
        journal_revision="journal-revision-001",
        read_started_at="2026-11-15T10:01:30Z",
        read_completed_at="2026-11-15T10:01:35Z",
    )
    values.update(overrides)
    return ReconciliationSnapshotReadReceipt.for_snapshot(**values)


def test_principal_requires_identity_and_timezone_aware_authentication_time():
    with pytest.raises(ValueError, match="subject"):
        principal(" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        AuthenticatedPrincipal("operator:a", "issuer", "webauthn", "2026-11-15T10:00:00")



def test_snapshot_receipt_binds_operation_journal_evidence_and_sources():
    valid = proposal()
    receipt = snapshot_receipt(valid.record, valid.evidence)
    bound = replace(valid, snapshot_receipt=receipt)

    receipt.verify_snapshot(bound.record, bound.evidence)
    assert receipt.operation_id == valid.record.operation_id
    assert receipt.evidence_sources == ("provider-observation",)
    assert receipt.approval_binding_digest()

    changed_record = replace(valid.record, updated_at="2026-11-15T09:11:00Z")
    with pytest.raises(ValueError, match="journal digest"):
        receipt.verify_snapshot(changed_record, valid.evidence)

    changed_evidence = (
        replace(valid.evidence[0], digest_sha256="f" * 64),
        *valid.evidence[1:],
    )
    with pytest.raises(ValueError, match="evidence digest"):
        receipt.verify_snapshot(valid.record, changed_evidence)


def test_snapshot_receipt_uses_journal_revision_fence():
    valid = proposal()
    receipt = snapshot_receipt(valid.record, valid.evidence)
    with pytest.raises(ValueError, match="journal revision changed"):
        replace(receipt, journal_revision_after="journal-revision-002")


def test_snapshot_approval_binding_is_stable_across_fresh_reads_but_not_revisions():
    valid = proposal()
    first = snapshot_receipt(
        valid.record,
        valid.evidence,
        snapshot_id="snapshot-first",
        read_started_at="2026-11-15T10:01:30Z",
        read_completed_at="2026-11-15T10:01:35Z",
    )
    reread = snapshot_receipt(
        valid.record,
        valid.evidence,
        snapshot_id="snapshot-second",
        read_started_at="2026-11-15T10:02:00Z",
        read_completed_at="2026-11-15T10:02:02Z",
    )
    different_revision = snapshot_receipt(
        valid.record,
        valid.evidence,
        journal_revision="journal-revision-002",
    )

    assert first.approval_binding_digest() == reread.approval_binding_digest()
    assert first.approval_binding_digest() != different_revision.approval_binding_digest()


def test_proposal_rejects_snapshot_receipt_for_different_evidence():
    valid = proposal()
    receipt = snapshot_receipt(valid.record, valid.evidence)
    changed_evidence = (
        replace(valid.evidence[0], digest_sha256="e" * 64),
        *valid.evidence[1:],
    )
    with pytest.raises(ValueError, match="snapshot receipt evidence digest"):
        replace(valid, evidence=changed_evidence, snapshot_receipt=receipt)


def test_approval_requires_distinct_requester_and_approver():
    with pytest.raises(ValueError, match="distinct"):
        approval(approved_by=principal("operator:requester"))


def test_approval_is_bound_to_reconciliation_phase_and_valid_time_window():
    with pytest.raises(ValueError, match="needs_reconciliation"):
        approval(expected_phase="traffic_switched")
    with pytest.raises(ValueError, match="expiry"):
        approval(expires_at="2026-11-15T09:59:00Z")


def test_proposal_accepts_abort_candidate_only_with_required_identity_bound_evidence():
    result = proposal()
    assert result.approval.operation == "abort_candidate"
    assert len(result.evidence) == 4


def test_proposal_accepts_previous_retired_only_with_required_identity_bound_evidence():
    result = proposal("confirm_previous_retired")
    assert result.approval.operation == "confirm_previous_retired"
    assert len(result.evidence) == 4


def test_proposal_rejects_scope_or_runtime_identity_mismatch():
    bad = approval(project="other-project")
    with pytest.raises(ValueError, match="project"):
        proposal(approval=bad)
    bad_runtime = approval(candidate_runtime_id="mutable-container-name")
    with pytest.raises(ValueError, match="candidate runtime"):
        proposal(approval=bad_runtime)


def test_proposal_rejects_missing_runtime_identity_and_non_reconciliation_phase():
    with pytest.raises(ValueError, match="immutable runtime"):
        proposal(record=journal(candidate_runtime_id=None))
    with pytest.raises(ValueError, match="needs_reconciliation"):
        proposal(record=journal(phase="traffic_switched"))


def test_proposal_rejects_incomplete_or_duplicate_evidence():
    valid = proposal()
    with pytest.raises(ValueError, match="evidence kinds"):
        replace(valid, evidence=valid.evidence[:-1])
    with pytest.raises(ValueError, match="unique"):
        replace(valid, evidence=(valid.evidence[0], valid.evidence[0], *valid.evidence[2:]))


def test_proposal_rejects_evidence_that_names_the_wrong_runtime():
    valid = proposal()
    wrong = replace(
        valid.evidence[1],
        subject_runtime_id="runtime-other",
    )
    with pytest.raises(ValueError, match="candidate absence"):
        replace(valid, evidence=(valid.evidence[0], wrong, *valid.evidence[2:]))


def test_evidence_requires_sha256_and_timezone_aware_observation():
    with pytest.raises(ValueError, match="SHA-256"):
        evidence("candidate_health", 1, digest_sha256="not-a-digest")
    with pytest.raises(ValueError, match="timezone-aware"):
        evidence("candidate_health", 1, observed_at="2026-11-15T10:00:00")

def test_evidence_digest_is_stable_across_fresh_reads_but_binds_semantic_changes():
    valid = proposal()
    refreshed = tuple(
        replace(
            item,
            evidence_id=f"fresh-{index}",
            observed_at="2026-11-15T10:00:30Z",
        )
        for index, item in enumerate(valid.evidence)
    )

    assert reconciliation_evidence_digest(valid.evidence) == reconciliation_evidence_digest(
        refreshed
    )

    changed = (
        replace(refreshed[0], digest_sha256="f" * 64),
        *refreshed[1:],
    )
    assert reconciliation_evidence_digest(valid.evidence) != reconciliation_evidence_digest(
        changed
    )



@pytest.mark.parametrize("operation", ["abort_candidate", "confirm_previous_retired"])
def test_proposal_accepts_host_synchronous_completion_evidence_as_distinct_alternative(operation):
    valid = proposal(operation)
    converted = (
        replace(
            valid.evidence[0],
            kind="host_synchronous_operation_completion",
            source="docker-local-host-call-receipts",
        ),
        *valid.evidence[1:],
    )
    result = replace(valid, evidence=converted)
    assert result.evidence[0].kind == "host_synchronous_operation_completion"
    assert result.approval.operation == operation


def test_proposal_rejects_mixed_native_and_host_completion_evidence():
    valid = proposal("abort_candidate")
    mixed = (
        valid.evidence[0],
        replace(
            valid.evidence[1],
            kind="host_synchronous_operation_completion",
            source="docker-local-host-call-receipts",
        ),
        *valid.evidence[2:],
    )
    with pytest.raises(ValueError, match="evidence kinds"):
        replace(valid, evidence=mixed)
