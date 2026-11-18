"""Data-only hash-linked audit envelopes for deployment reconciliation.

This module does not persist events, authenticate actors, sign records, or
mutate deployment journals. A hash chain detects edits/reordering only when
its trusted head is anchored outside the writable audit store.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from runtime.deployment_reconciliation_contract import AuthenticatedPrincipal

AuditAction = Literal[
    "reconciliation_proposed",
    "reconciliation_approved",
    "reconciliation_approval_consumption_started",
    "reconciliation_approval_consumption_started",
    "reconciliation_approval_consumed",
    "reconciliation_applied",
    "reconciliation_rejected",
]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ZERO_DIGEST = "0" * 64
_ACTIONS = {
    "reconciliation_proposed",
    "reconciliation_approved",
    "reconciliation_approval_consumed",
    "reconciliation_applied",
    "reconciliation_rejected",
}


def _aware(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("recorded_at must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("recorded_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")


def _digest(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")


def _canonical_payload(
    *,
    event_id: str,
    sequence: int,
    previous_digest: str,
    action: str,
    actor: AuthenticatedPrincipal,
    approval_id: str,
    operation_id: str,
    provider: str,
    project: str,
    environment: str,
    journal_phase: str,
    target_deployment_id: str,
    previous_deployment_id: str,
    candidate_runtime_id: str,
    previous_runtime_id: str,
    proposal_digest: str,
    evidence_digest: str,
    recorded_at: str,
    approval_token_digest: str | None = None,
    approval_expires_at: str | None = None,
) -> bytes:
    payload = {
        "event_id": event_id,
        "sequence": sequence,
        "previous_digest": previous_digest,
        "action": action,
        "actor": asdict(actor),
        "approval_id": approval_id,
        "operation_id": operation_id,
        "provider": provider,
        "project": project,
        "environment": environment,
        "journal_phase": journal_phase,
        "target_deployment_id": target_deployment_id,
        "previous_deployment_id": previous_deployment_id,
        "candidate_runtime_id": candidate_runtime_id,
        "previous_runtime_id": previous_runtime_id,
        "proposal_digest": proposal_digest,
        "evidence_digest": evidence_digest,
        "recorded_at": recorded_at,
    }
    # Omit absent extension fields so pre-extension v1 events retain their
    # original canonical bytes and remain verifiable without migration.
    if approval_token_digest is not None:
        payload["approval_token_digest"] = approval_token_digest
    if approval_expires_at is not None:
        payload["approval_expires_at"] = approval_expires_at
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


@dataclass(frozen=True)
class ReconciliationAuditEnvelope:
    """Immutable audit event snapshot; construction is not durable recording."""

    event_id: str
    sequence: int
    previous_digest: str
    action: AuditAction
    actor: AuthenticatedPrincipal
    approval_id: str
    operation_id: str
    provider: str
    project: str
    environment: str
    journal_phase: str
    target_deployment_id: str
    previous_deployment_id: str
    candidate_runtime_id: str
    previous_runtime_id: str
    proposal_digest: str
    evidence_digest: str
    recorded_at: str
    event_digest: str
    approval_token_digest: str | None = None
    approval_expires_at: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "event_id", "approval_id", "operation_id", "provider", "project",
            "environment", "journal_phase", "target_deployment_id",
            "previous_deployment_id", "candidate_runtime_id", "previous_runtime_id",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if self.action not in _ACTIONS:
            raise ValueError("unsupported reconciliation audit action")
        if not isinstance(self.actor, AuthenticatedPrincipal):
            raise TypeError("actor must be an AuthenticatedPrincipal snapshot")
        if self.previous_digest != _ZERO_DIGEST:
            _digest(self.previous_digest, "previous_digest")
        if self.target_deployment_id == self.previous_deployment_id:
            raise ValueError("target and previous deployment identities must differ")
        if self.candidate_runtime_id == self.previous_runtime_id:
            raise ValueError("candidate and previous runtime identities must differ")
        _digest(self.proposal_digest, "proposal_digest")
        _digest(self.evidence_digest, "evidence_digest")
        _aware(self.recorded_at)
        if (self.approval_token_digest is None) != (self.approval_expires_at is None):
            raise ValueError("approval token digest and expiry must be recorded together")
        if self.approval_token_digest is not None:
            if self.action != "reconciliation_approved":
                raise ValueError("approval token metadata is only valid on approval events")
            _digest(self.approval_token_digest, "approval_token_digest")
            _aware(self.approval_expires_at)
        _digest(self.event_digest, "event_digest")
        expected = hashlib.sha256(self.canonical_payload()).hexdigest()
        if self.event_digest != expected:
            raise ValueError("event_digest does not match canonical audit payload")
        if self.sequence == 1 and self.previous_digest != _ZERO_DIGEST:
            raise ValueError("first audit event must use the zero previous digest")
        if self.sequence > 1 and self.previous_digest == _ZERO_DIGEST:
            raise ValueError("non-first audit event must link a previous digest")

    def canonical_payload(self) -> bytes:
        return _canonical_payload(
            event_id=self.event_id,
            sequence=self.sequence,
            previous_digest=self.previous_digest,
            action=self.action,
            actor=self.actor,
            approval_id=self.approval_id,
            operation_id=self.operation_id,
            provider=self.provider,
            project=self.project,
            environment=self.environment,
            journal_phase=self.journal_phase,
            target_deployment_id=self.target_deployment_id,
            previous_deployment_id=self.previous_deployment_id,
            candidate_runtime_id=self.candidate_runtime_id,
            previous_runtime_id=self.previous_runtime_id,
            proposal_digest=self.proposal_digest,
            evidence_digest=self.evidence_digest,
            recorded_at=self.recorded_at,
            approval_token_digest=self.approval_token_digest,
            approval_expires_at=self.approval_expires_at,
        )

    def verify_successor_of(self, previous: ReconciliationAuditEnvelope) -> None:
        """Reject a broken sequence/link; callers must separately anchor the head."""
        if not isinstance(previous, ReconciliationAuditEnvelope):
            raise TypeError("previous must be a ReconciliationAuditEnvelope")
        if self.sequence != previous.sequence + 1:
            raise ValueError("audit sequence is not contiguous")
        if self.previous_digest != previous.event_digest:
            raise ValueError("audit previous_digest does not match prior event")
