"""Data-only authorization and evidence contracts for deployment reconciliation.

This module does not authenticate principals, issue/consume approvals, append
audit events, mutate journals, or invoke deployment providers. Those duties
remain with a future trusted host boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from runtime.deployment_replacement import ReplacementJournalRecord

ReconciliationOperation = Literal["abort_candidate", "confirm_previous_retired"]
EvidenceKind = Literal[
    "provider_operation_inspection",
    "candidate_absence",
    "previous_runtime_inspection",
    "previous_route_readback",
    "candidate_route_readback",
    "candidate_health",
    "previous_runtime_retirement",
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPERATIONS = {"abort_candidate", "confirm_previous_retired"}
_REQUIRED_EVIDENCE = {
    "abort_candidate": {
        "provider_operation_inspection",
        "candidate_absence",
        "previous_runtime_inspection",
        "previous_route_readback",
    },
    "confirm_previous_retired": {
        "provider_operation_inspection",
        "candidate_route_readback",
        "candidate_health",
        "previous_runtime_retirement",
    },
}


def _non_empty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _aware(value: str, field: str) -> datetime:
    _non_empty(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Host-authenticated identity snapshot; construction does not authenticate."""

    subject: str
    issuer: str
    authentication_method: str
    authenticated_at: str

    def __post_init__(self) -> None:
        for field in ("subject", "issuer", "authentication_method"):
            _non_empty(getattr(self, field), field)
        _aware(self.authenticated_at, "authenticated_at")


@dataclass(frozen=True)
class ReconciliationApproval:
    """Approval snapshot bound to one exact journal revision and resolution."""

    approval_id: str
    operation: ReconciliationOperation
    provider: str
    project: str
    environment: str
    operation_id: str
    expected_phase: str
    target_deployment_id: str
    previous_deployment_id: str
    candidate_runtime_id: str
    previous_runtime_id: str
    requested_by: AuthenticatedPrincipal
    approved_by: AuthenticatedPrincipal
    issued_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if self.operation not in _OPERATIONS:
            raise ValueError("unsupported reconciliation operation")
        for field in (
            "approval_id", "provider", "project", "environment", "operation_id",
            "target_deployment_id", "previous_deployment_id", "candidate_runtime_id",
            "previous_runtime_id",
        ):
            _non_empty(getattr(self, field), field)
        if self.expected_phase != "needs_reconciliation":
            raise ValueError("approval must bind to needs_reconciliation phase")
        if self.target_deployment_id == self.previous_deployment_id:
            raise ValueError("target and previous deployment identities must differ")
        if self.candidate_runtime_id == self.previous_runtime_id:
            raise ValueError("candidate and previous runtime identities must differ")
        if not isinstance(self.requested_by, AuthenticatedPrincipal) or not isinstance(
            self.approved_by, AuthenticatedPrincipal
        ):
            raise TypeError("requester and approver must be principal snapshots")
        if (
            self.requested_by.issuer,
            self.requested_by.subject,
        ) == (
            self.approved_by.issuer,
            self.approved_by.subject,
        ):
            raise ValueError("requester and approver must be distinct principals")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("approval expiry must be later than issuance")


@dataclass(frozen=True)
class ReconciliationEvidence:
    """Digest-addressed observation; source authenticity is verified by the host."""

    evidence_id: str
    kind: EvidenceKind
    source: str
    observed_at: str
    digest_sha256: str
    subject_runtime_id: str | None = None
    observed_runtime_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("evidence_id", "source"):
            _non_empty(getattr(self, field), field)
        if self.kind not in set().union(*_REQUIRED_EVIDENCE.values()):
            raise ValueError("unsupported reconciliation evidence kind")
        _aware(self.observed_at, "observed_at")
        if not isinstance(self.digest_sha256, str) or not _SHA256.fullmatch(
            self.digest_sha256
        ):
            raise ValueError("digest_sha256 must be a lowercase SHA-256 hex digest")
        for field in ("subject_runtime_id", "observed_runtime_id"):
            value = getattr(self, field)
            if value is not None:
                _non_empty(value, field)


@dataclass(frozen=True)
class ReconciliationProposal:
    """Validated proposal only; it cannot commit a journal transition."""

    record: ReplacementJournalRecord
    approval: ReconciliationApproval
    evidence: tuple[ReconciliationEvidence, ...]
    proposed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, ReplacementJournalRecord):
            raise TypeError("record must be a ReplacementJournalRecord")
        if not isinstance(self.approval, ReconciliationApproval):
            raise TypeError("approval must be a ReconciliationApproval")
        if self.record.phase != "needs_reconciliation":
            raise ValueError("only needs_reconciliation records can be proposed")
        if self.record.candidate_runtime_id is None or self.record.previous_runtime_id is None:
            raise ValueError("both immutable runtime identities are required")
        approval = self.approval
        for field in (
            "provider", "project", "environment", "operation_id",
            "target_deployment_id", "previous_deployment_id",
        ):
            if getattr(approval, field) != getattr(self.record, field):
                raise ValueError(f"approval {field} does not match journal snapshot")
        if approval.candidate_runtime_id != self.record.candidate_runtime_id:
            raise ValueError("approval candidate runtime identity does not match journal")
        if approval.previous_runtime_id != self.record.previous_runtime_id:
            raise ValueError("approval previous runtime identity does not match journal")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, ReconciliationEvidence) for item in self.evidence
        ):
            raise TypeError("evidence must be a tuple of ReconciliationEvidence")
        ids = [item.evidence_id for item in self.evidence]
        kinds = [item.kind for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence identifiers must be unique")
        if len(kinds) != len(set(kinds)):
            raise ValueError("evidence kinds must be unique")
        required = _REQUIRED_EVIDENCE[approval.operation]
        if set(kinds) != required:
            raise ValueError("evidence kinds do not satisfy the resolution policy")
        by_kind = {item.kind: item for item in self.evidence}
        candidate = self.record.candidate_runtime_id
        previous = self.record.previous_runtime_id
        if approval.operation == "abort_candidate":
            if by_kind["candidate_absence"].subject_runtime_id != candidate:
                raise ValueError("candidate absence evidence must identify the candidate runtime")
            if by_kind["previous_runtime_inspection"].subject_runtime_id != previous:
                raise ValueError("previous runtime evidence must identify the previous runtime")
            if by_kind["previous_route_readback"].observed_runtime_id != previous:
                raise ValueError("previous route read-back must target the previous runtime")
        else:
            if by_kind["candidate_route_readback"].observed_runtime_id != candidate:
                raise ValueError("candidate route read-back must target the candidate runtime")
            if by_kind["candidate_health"].subject_runtime_id != candidate:
                raise ValueError("candidate health evidence must identify the candidate runtime")
            if by_kind["previous_runtime_retirement"].subject_runtime_id != previous:
                raise ValueError("retirement evidence must identify the previous runtime")
        _aware(self.proposed_at, "proposed_at")
