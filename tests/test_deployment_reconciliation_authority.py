from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from runtime.deployment_reconciliation_audit_store import DurableReconciliationAuditStore
from runtime.deployment_reconciliation_authority import (
    ReconciliationApprovalAuthority,
    ReconciliationApprovalGrant,
    ReconciliationAuthorizationError,
    ReconciliationCurrentSnapshot,
    VerifiedHostAuthentication,
)
from runtime.deployment_reconciliation_contract import (
    AuthenticatedPrincipal,
    ReconciliationApproval,
    ReconciliationEvidence,
    ReconciliationProposal,
)
from runtime.deployment_replacement import ReplacementJournalRecord


class _Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


class _Authenticator:
    def __init__(self, principals):
        self.principals = principals
        self.challenges = []

    def authenticate(self, challenge, response):
        self.challenges.append(challenge)
        if response not in self.principals:
            raise PermissionError("invalid test proof")
        return VerifiedHostAuthentication(
            principal=self.principals[response],
            challenge_id=challenge.challenge_id,
            nonce_sha256=hashlib.sha256(challenge.nonce.encode("utf-8")).hexdigest(),
            audience=challenge.audience,
            purpose=challenge.purpose,
            operation=challenge.operation,
            scope_digest=challenge.scope_digest,
        )


class _SnapshotReader:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []
        self.error = None

    def read_current_snapshot(self, operation_id):
        self.calls.append(operation_id)
        if self.error is not None:
            raise self.error
        return self.snapshot


def _principal(subject, *, issuer="https://id.example.test", method="webauthn"):
    return AuthenticatedPrincipal(
        subject=subject,
        issuer=issuer,
        authentication_method=method,
        authenticated_at="2026-11-18T10:00:00Z",
    )


def _proposal():
    record = ReplacementJournalRecord(
        operation_id="replace-001",
        provider="docker-local",
        project="demo",
        environment="staging",
        target_deployment_id="release-new",
        previous_deployment_id="release-current",
        phase="needs_reconciliation",
        created_at="2026-11-18T09:00:00Z",
        updated_at="2026-11-18T09:10:00Z",
        candidate_runtime_id="runtime-candidate-immutable",
        previous_runtime_id="runtime-previous-immutable",
    )
    template = ReconciliationApproval(
        approval_id="template-approval",
        operation="abort_candidate",
        provider=record.provider,
        project=record.project,
        environment=record.environment,
        operation_id=record.operation_id,
        expected_phase="needs_reconciliation",
        target_deployment_id=record.target_deployment_id,
        previous_deployment_id=record.previous_deployment_id,
        candidate_runtime_id=record.candidate_runtime_id,
        previous_runtime_id=record.previous_runtime_id,
        requested_by=_principal("untrusted-template-requester"),
        approved_by=_principal("untrusted-template-approver"),
        issued_at="2026-11-18T09:11:00Z",
        expires_at="2026-11-18T09:16:00Z",
    )
    evidence = (
        ReconciliationEvidence(
            evidence_id="ev-1",
            kind="provider_operation_inspection",
            source="docker-inspect",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="1" * 64,
        ),
        ReconciliationEvidence(
            evidence_id="ev-2",
            kind="candidate_absence",
            source="docker-inspect",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="2" * 64,
            subject_runtime_id=record.candidate_runtime_id,
        ),
        ReconciliationEvidence(
            evidence_id="ev-3",
            kind="previous_runtime_inspection",
            source="docker-inspect",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="3" * 64,
            subject_runtime_id=record.previous_runtime_id,
        ),
        ReconciliationEvidence(
            evidence_id="ev-4",
            kind="previous_route_readback",
            source="haproxy-runtime-api",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="4" * 64,
            observed_runtime_id=record.previous_runtime_id,
        ),
    )
    return ReconciliationProposal(
        record=record,
        approval=template,
        evidence=evidence,
        proposed_at="2026-11-18T09:59:45Z",
    )


def _authority(tmp_path, principals, *, clock=None, snapshot_reader=None, **kwargs):
    proposal = _proposal()
    reader = snapshot_reader or _SnapshotReader(
        ReconciliationCurrentSnapshot(proposal.record, proposal.evidence)
    )
    return ReconciliationApprovalAuthority(
        authenticator=_Authenticator(principals),
        snapshot_reader=reader,
        trusted_issuers=frozenset({"https://id.example.test"}),
        trusted_authentication_methods=frozenset({"webauthn"}),
        authentication_audience="urn:ai-team:deployment-reconciliation",
        audit_store=DurableReconciliationAuditStore(tmp_path),
        clock=clock or _Clock(),
        **kwargs,
    )


@pytest.mark.parametrize(
    "field",
    ("challenge_id", "nonce_sha256", "audience", "purpose", "operation", "scope_digest"),
)
def test_authentication_receipt_must_match_issued_challenge(tmp_path, field):
    class _MismatchedAuthenticator(_Authenticator):
        def authenticate(self, challenge, response):
            receipt = super().authenticate(challenge, response)
            replacement = "approver" if field == "purpose" else "mismatched-value"
            if field == "nonce_sha256":
                replacement = "0" * 64
            return replace(receipt, **{field: replacement})

    proposal = _proposal()
    reader = _SnapshotReader(
        ReconciliationCurrentSnapshot(proposal.record, proposal.evidence)
    )
    authority = ReconciliationApprovalAuthority(
        authenticator=_MismatchedAuthenticator(
            {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")}
        ),
        snapshot_reader=reader,
        trusted_issuers=frozenset({"https://id.example.test"}),
        trusted_authentication_methods=frozenset({"webauthn"}),
        authentication_audience="urn:ai-team:deployment-reconciliation",
        audit_store=DurableReconciliationAuditStore(tmp_path),
        clock=_Clock(),
    )
    with pytest.raises(
        ReconciliationAuthorizationError, match="receipt does not match"
    ):
        authority.authorize_proposal(
            proposal,
            requester_response="requester-proof",
            approver_response="approver-proof",
        )
    assert not authority._audit.events(operation_id=proposal.record.operation_id)


def test_host_authenticator_must_return_challenge_bound_receipt(tmp_path):
    class _LegacyAuthenticator:
        def authenticate(self, challenge, response):
            return _principal("alice")

    proposal = _proposal()
    reader = _SnapshotReader(
        ReconciliationCurrentSnapshot(proposal.record, proposal.evidence)
    )
    authority = ReconciliationApprovalAuthority(
        authenticator=_LegacyAuthenticator(),
        snapshot_reader=reader,
        trusted_issuers=frozenset({"https://id.example.test"}),
        trusted_authentication_methods=frozenset({"webauthn"}),
        authentication_audience="urn:ai-team:deployment-reconciliation",
        audit_store=DurableReconciliationAuditStore(tmp_path),
        clock=_Clock(),
    )

    with pytest.raises(
        ReconciliationAuthorizationError, match="challenge-binding receipt"
    ):
        authority.authorize_proposal(
            proposal,
            requester_response="principal-only",
            approver_response="approver-proof",
        )
    assert not authority._audit.events(operation_id=proposal.record.operation_id)


def test_authority_requires_explicit_trusted_dependencies(tmp_path):
    with pytest.raises(TypeError, match="HostAuthenticator"):
        ReconciliationApprovalAuthority(
            authenticator=None,
            snapshot_reader=_SnapshotReader(
                ReconciliationCurrentSnapshot(_proposal().record, _proposal().evidence)
            ),
            trusted_issuers=frozenset({"issuer"}),
            trusted_authentication_methods=frozenset({"webauthn"}),
            audit_store=DurableReconciliationAuditStore(tmp_path),
        )


def test_authentication_audience_is_required(tmp_path):
    with pytest.raises(ValueError, match="authentication_audience"):
        _authority(
            tmp_path,
            {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")},
            authentication_audience=" ",
        )


def test_authorize_uses_authenticated_principals_not_template_identity(tmp_path):
    requester = _principal("alice")
    approver = _principal("bob")
    authority = _authority(
        tmp_path,
        {"requester-proof": requester, "approver-proof": approver},
    )
    proposal = _proposal()

    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )

    assert grant.proposal.approval.requested_by == requester
    assert grant.proposal.approval.approved_by == approver
    assert grant.proposal.approval.approval_id != "template-approval"
    assert grant.proposal.approval.expires_at == "2026-11-18T10:05:00Z"
    assert authority._authenticator.challenges[0].purpose == "requester"
    assert authority._authenticator.challenges[1].purpose == "approver"
    assert authority._authenticator.challenges[0].audience == "urn:ai-team:deployment-reconciliation"
    assert authority._authenticator.challenges[1].audience == "urn:ai-team:deployment-reconciliation"
    assert authority._authenticator.challenges[0].scope_digest == grant.proposal_digest
    assert authority._authenticator.challenges[1].scope_digest == grant.proposal_digest
    assert authority._authenticator.challenges[1].requester_subject == "alice"


def test_dual_approval_is_durable_and_consumed_once(tmp_path):
    requester, approver = _principal("alice"), _principal("bob")
    authority = _authority(
        tmp_path,
        {"requester-proof": requester, "approver-proof": approver},
    )
    proposal = _proposal()
    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )
    approved = authority.consume(grant)
    assert authority._snapshot_reader.calls == ["replace-001"]
    assert approved.approval.requested_by == requester
    assert approved.approval.approved_by == approver

    events = authority._audit.events(operation_id=proposal.record.operation_id)
    assert [event.action for event in events] == [
        "reconciliation_proposed",
        "reconciliation_approved",
        "reconciliation_approval_consumed",
    ]
    assert [event.actor.subject for event in events] == ["alice", "bob", "bob"]
    with pytest.raises(ReconciliationAuthorizationError, match="already consumed"):
        authority.consume(grant)


def test_same_principal_cannot_request_and_approve(tmp_path):
    alice = _principal("alice")
    authority = _authority(
        tmp_path, {"requester-proof": alice, "approver-proof": alice}
    )
    with pytest.raises(ReconciliationAuthorizationError, match="distinct"):
        authority.authorize_proposal(
            _proposal(),
            requester_response="requester-proof",
            approver_response="approver-proof",
        )
    events = authority._audit.events(operation_id="replace-001")
    assert [event.action for event in events] == [
        "reconciliation_proposed",
        "reconciliation_rejected",
    ]


def test_untrusted_issuer_or_authentication_method_is_rejected(tmp_path):
    bad_issuer = _principal("alice", issuer="https://untrusted.example.test")
    authority = _authority(
        tmp_path,
        {"requester-proof": bad_issuer, "approver-proof": _principal("bob")},
    )
    with pytest.raises(ReconciliationAuthorizationError, match="issuer"):
        authority.authorize_proposal(
            _proposal(),
            requester_response="requester-proof",
            approver_response="approver-proof",
        )

    bad_method = _principal("alice", method="password-only")
    authority = _authority(
        tmp_path / "method",
        {"requester-proof": bad_method, "approver-proof": _principal("bob")},
    )
    with pytest.raises(ReconciliationAuthorizationError, match="method"):
        authority.authorize_proposal(
            _proposal(),
            requester_response="requester-proof",
            approver_response="approver-proof",
        )


def test_approval_is_bound_to_exact_journal_and_evidence_snapshot(tmp_path):
    requester, approver = _principal("alice"), _principal("bob")
    authority = _authority(
        tmp_path,
        {"requester-proof": requester, "approver-proof": approver},
    )
    proposal = _proposal()
    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )
    changed_record = replace(proposal.record, updated_at="2026-11-18T09:12:00Z")
    authority._snapshot_reader.snapshot = ReconciliationCurrentSnapshot(
        changed_record, proposal.evidence
    )
    with pytest.raises(ReconciliationAuthorizationError, match="journal revision"):
        authority.consume(grant)
    with pytest.raises(ReconciliationAuthorizationError, match="unknown"):
        authority.consume(grant)

    grant2 = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )
    changed_evidence = (
        replace(proposal.evidence[0], digest_sha256="f" * 64),
        *proposal.evidence[1:],
    )
    authority._snapshot_reader.snapshot = ReconciliationCurrentSnapshot(
        proposal.record, changed_evidence
    )
    with pytest.raises(ReconciliationAuthorizationError, match="evidence changed"):
        authority.consume(grant2)


def test_expired_grant_is_burned_and_never_consumed(tmp_path):
    clock = _Clock()
    requester, approver = _principal("alice"), _principal("bob")
    authority = _authority(
        tmp_path,
        {"requester-proof": requester, "approver-proof": approver},
        clock=clock,
        approval_ttl_seconds=30,
    )
    proposal = _proposal()
    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )
    clock.value += timedelta(seconds=30)
    with pytest.raises(ReconciliationAuthorizationError, match="expired"):
        authority.consume(grant)
    with pytest.raises(ReconciliationAuthorizationError, match="unknown"):
        authority.consume(grant)


def test_authentication_challenge_must_not_be_replayed_after_expiry(tmp_path):
    clock = _Clock()
    challenge_ttl = 15

    class _SlowAuthenticator(_Authenticator):
        def authenticate(self, challenge, response):
            clock.value += timedelta(seconds=challenge_ttl + 1)
            return super().authenticate(challenge, response)

    authenticator = _SlowAuthenticator(
        {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")}
    )
    proposal = _proposal()
    authority = ReconciliationApprovalAuthority(
        authenticator=authenticator,
        snapshot_reader=_SnapshotReader(
            ReconciliationCurrentSnapshot(proposal.record, proposal.evidence)
        ),
        trusted_issuers=frozenset({"https://id.example.test"}),
        trusted_authentication_methods=frozenset({"webauthn"}),
        authentication_audience="urn:ai-team:deployment-reconciliation",
        audit_store=DurableReconciliationAuditStore(tmp_path),
        challenge_ttl_seconds=challenge_ttl,
        clock=clock,
    )
    with pytest.raises(ReconciliationAuthorizationError, match="challenge expired"):
        authority.authorize_proposal(
            _proposal(),
            requester_response="requester-proof",
            approver_response="approver-proof",
        )


def test_stale_evidence_is_rejected_before_requester_authentication(tmp_path):
    proposal = _proposal()
    stale_evidence = replace(
        proposal.evidence[0],
        observed_at="2026-11-18T09:54:59Z",
    )
    stale_proposal = replace(
        proposal,
        evidence=(stale_evidence, *proposal.evidence[1:]),
    )
    authority = _authority(
        tmp_path,
        {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")},
    )
    with pytest.raises(ReconciliationAuthorizationError, match="evidence is stale"):
        authority.authorize_proposal(
            stale_proposal,
            requester_response="requester-proof",
            approver_response="approver-proof",
        )
    assert authority._authenticator.challenges == []
    assert not authority._audit.events(operation_id=proposal.record.operation_id)


def test_evidence_ages_out_during_current_snapshot_read(tmp_path):
    clock = _Clock()
    proposal = _proposal()

    class _AgingSnapshotReader(_SnapshotReader):
        def read_current_snapshot(self, operation_id):
            snapshot = super().read_current_snapshot(operation_id)
            clock.value += timedelta(seconds=301)
            return snapshot

    reader = _AgingSnapshotReader(
        ReconciliationCurrentSnapshot(proposal.record, proposal.evidence)
    )
    authority = _authority(
        tmp_path,
        {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")},
        clock=clock,
        snapshot_reader=reader,
        approval_ttl_seconds=600,
        evidence_max_age_seconds=300,
    )
    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )

    with pytest.raises(ReconciliationAuthorizationError, match="evidence is stale"):
        authority.consume(grant)
    events = authority._audit.events(operation_id=proposal.record.operation_id)
    assert [event.action for event in events] == [
        "reconciliation_proposed",
        "reconciliation_approved",
    ]
    with pytest.raises(ReconciliationAuthorizationError, match="unknown"):
        authority.consume(grant)


def test_approval_expires_while_current_snapshot_is_read(tmp_path):
    clock = _Clock()
    proposal = _proposal()

    class _SlowSnapshotReader(_SnapshotReader):
        def read_current_snapshot(self, operation_id):
            snapshot = super().read_current_snapshot(operation_id)
            clock.value += timedelta(seconds=30)
            return snapshot

    reader = _SlowSnapshotReader(
        ReconciliationCurrentSnapshot(proposal.record, proposal.evidence)
    )
    authority = _authority(
        tmp_path,
        {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")},
        clock=clock,
        snapshot_reader=reader,
        approval_ttl_seconds=30,
    )
    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )

    with pytest.raises(ReconciliationAuthorizationError, match="expired"):
        authority.consume(grant)
    events = authority._audit.events(operation_id=proposal.record.operation_id)
    assert [event.action for event in events] == [
        "reconciliation_proposed",
        "reconciliation_approved",
    ]
    with pytest.raises(ReconciliationAuthorizationError, match="unknown"):
        authority.consume(grant)


def test_snapshot_read_failure_burns_approval_grant(tmp_path):
    proposal = _proposal()
    reader = _SnapshotReader(
        ReconciliationCurrentSnapshot(proposal.record, proposal.evidence)
    )
    authority = _authority(
        tmp_path,
        {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")},
        snapshot_reader=reader,
    )
    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )
    reader.error = OSError("journal unavailable")
    with pytest.raises(
        ReconciliationAuthorizationError, match="snapshot read failed"
    ):
        authority.consume(grant)
    reader.error = None
    with pytest.raises(ReconciliationAuthorizationError, match="unknown"):
        authority.consume(grant)


def test_consume_does_not_accept_caller_supplied_current_snapshot(tmp_path):
    proposal = _proposal()
    authority = _authority(
        tmp_path,
        {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")},
    )
    grant = authority.authorize_proposal(
        proposal,
        requester_response="requester-proof",
        approver_response="approver-proof",
    )
    with pytest.raises(TypeError):
        authority.consume(
            grant,
            current_record=proposal.record,
            current_evidence=proposal.evidence,
        )
    # A rejected API call does not consume the grant; the trusted reader still can.
    assert authority.consume(grant).record == proposal.record


def test_authority_has_no_deployment_mutation_surface(tmp_path):
    authority = _authority(
        tmp_path,
        {"requester-proof": _principal("alice"), "approver-proof": _principal("bob")},
    )
    for name in (
        "replace", "rollback", "stop", "cleanup", "switch_traffic", "update_journal"
    ):
        assert not hasattr(authority, name)
    grant = ReconciliationApprovalGrant(
        proposal=_proposal(),
        proposal_digest="a" * 64,
        evidence_digest="b" * 64,
        token="forged",
    )
    with pytest.raises(ReconciliationAuthorizationError, match="unknown"):
        authority.consume(grant)
