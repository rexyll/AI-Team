from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.deployment_reconciliation_contract import (
    AuthenticatedPrincipal,
    ReconciliationApproval,
    ReconciliationEvidence,
    ReconciliationProposal,
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


def test_principal_requires_identity_and_timezone_aware_authentication_time():
    with pytest.raises(ValueError, match="subject"):
        principal(" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        AuthenticatedPrincipal("operator:a", "issuer", "webauthn", "2026-11-15T10:00:00")


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
