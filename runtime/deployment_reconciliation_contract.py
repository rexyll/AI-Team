"""Data-only authorization and evidence contracts for deployment reconciliation.

This module does not authenticate principals, issue/consume approvals, append
audit events, mutate journals, or invoke deployment providers. Those duties
remain with a future trusted host boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from runtime.deployment_replacement import ReplacementJournalRecord

ReconciliationOperation = Literal["abort_candidate", "confirm_previous_retired"]
EvidenceKind = Literal[
    "provider_operation_inspection",
    "host_synchronous_operation_completion",
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
        if self.kind not in (
            set().union(*_REQUIRED_EVIDENCE.values())
            | {"host_synchronous_operation_completion"}
        ):
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


def reconciliation_record_digest(
    record: ReplacementJournalRecord,
) -> str:
    """Return the canonical digest for one immutable journal record snapshot."""
    if not isinstance(record, ReplacementJournalRecord):
        raise TypeError("record must be a ReplacementJournalRecord")
    payload = json.dumps(
        asdict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def reconciliation_evidence_digest(
    evidence: tuple[ReconciliationEvidence, ...],
) -> str:
    """Digest semantic evidence while leaving freshness timestamps out of the binding.

    Evidence observation timestamps and generated evidence IDs are deliberately
    validated separately: timestamps must be fresh and covered by the snapshot
    receipt, but repeated reads of an unchanged provider/runtime/route state
    should retain the same approval binding. The digest still binds each exact
    evidence kind, source ID, canonical response digest and immutable runtime
    identity claim.
    """
    if not isinstance(evidence, tuple) or any(
        not isinstance(item, ReconciliationEvidence) for item in evidence
    ):
        raise TypeError("evidence must be a tuple of ReconciliationEvidence")
    payload = [
        {
            "kind": item.kind,
            "source": item.source,
            "digest_sha256": item.digest_sha256,
            "subject_runtime_id": item.subject_runtime_id,
            "observed_runtime_id": item.observed_runtime_id,
        }
        for item in evidence
    ]
    payload.sort(key=lambda item: item["kind"])
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class ReconciliationSnapshotReadReceipt:
    """Provider-neutral receipt for a journal-revision-fenced Host read.

    The receipt is an assertion from the injected trusted reader, not a digital
    signature. The Host must authenticate each underlying source and protect
    the reader implementation/configuration as part of its trust boundary.
    """

    reader_id: str
    snapshot_id: str
    operation_id: str
    journal_revision_before: str
    journal_revision_after: str
    record_digest: str
    evidence_digest: str
    evidence_sources: tuple[str, ...]
    read_started_at: str
    read_completed_at: str
    consistency_model: Literal["journal_revision_fence"] = "journal_revision_fence"

    def __post_init__(self) -> None:
        for field in (
            "reader_id",
            "snapshot_id",
            "operation_id",
            "journal_revision_before",
            "journal_revision_after",
        ):
            _non_empty(getattr(self, field), field)
        if self.journal_revision_before != self.journal_revision_after:
            raise ValueError("journal revision changed during snapshot read")
        for field in ("record_digest", "evidence_digest"):
            value = getattr(self, field)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        if (
            not isinstance(self.evidence_sources, tuple)
            or not self.evidence_sources
            or any(not isinstance(item, str) or not item.strip() for item in self.evidence_sources)
        ):
            raise ValueError("evidence_sources must be a non-empty tuple of source identifiers")
        if tuple(sorted(set(self.evidence_sources))) != self.evidence_sources:
            raise ValueError("evidence_sources must be sorted and unique")
        started = _aware(self.read_started_at, "read_started_at")
        completed = _aware(self.read_completed_at, "read_completed_at")
        if completed < started:
            raise ValueError("read_completed_at must not precede read_started_at")
        if self.consistency_model != "journal_revision_fence":
            raise ValueError("unsupported snapshot consistency model")

    @classmethod
    def for_snapshot(
        cls,
        *,
        reader_id: str,
        snapshot_id: str,
        record: ReplacementJournalRecord,
        evidence: tuple[ReconciliationEvidence, ...],
        journal_revision: str,
        read_started_at: str,
        read_completed_at: str,
    ) -> "ReconciliationSnapshotReadReceipt":
        """Build the receipt after a Host reader has completed its fenced read."""
        return cls(
            reader_id=reader_id,
            snapshot_id=snapshot_id,
            operation_id=record.operation_id,
            journal_revision_before=journal_revision,
            journal_revision_after=journal_revision,
            record_digest=reconciliation_record_digest(record),
            evidence_digest=reconciliation_evidence_digest(evidence),
            evidence_sources=tuple(sorted({item.source for item in evidence})),
            read_started_at=read_started_at,
            read_completed_at=read_completed_at,
        )

    def verify_snapshot(
        self,
        record: ReplacementJournalRecord,
        evidence: tuple[ReconciliationEvidence, ...],
    ) -> None:
        """Check that this receipt names and hashes the supplied exact snapshot."""
        if self.operation_id != record.operation_id:
            raise ValueError("snapshot receipt operation_id does not match the journal")
        if self.record_digest != reconciliation_record_digest(record):
            raise ValueError("snapshot receipt journal digest does not match the record")
        if self.evidence_digest != reconciliation_evidence_digest(evidence):
            raise ValueError("snapshot receipt evidence digest does not match the evidence")
        sources = tuple(sorted({item.source for item in evidence}))
        if self.evidence_sources != sources:
            raise ValueError("snapshot receipt evidence sources do not match the evidence")

    def approval_binding_digest(self) -> str:
        """Stable provenance binding used by the proposal approval digest.

        Snapshot IDs and read timestamps identify an individual read and change
        on re-read. The stable binding covers reader, journal revision, source
        set, operation and consistency model instead.
        """
        payload = {
            "reader_id": self.reader_id,
            "operation_id": self.operation_id,
            "journal_revision": self.journal_revision_after,
            "record_digest": self.record_digest,
            "evidence_digest": self.evidence_digest,
            "evidence_sources": list(self.evidence_sources),
            "consistency_model": self.consistency_model,
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class ReconciliationProposal:
    """Validated proposal only; it cannot commit a journal transition."""

    record: ReplacementJournalRecord
    approval: ReconciliationApproval
    evidence: tuple[ReconciliationEvidence, ...]
    proposed_at: str
    snapshot_receipt: ReconciliationSnapshotReadReceipt | None = None

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
        if self.snapshot_receipt is not None:
            if not isinstance(self.snapshot_receipt, ReconciliationSnapshotReadReceipt):
                raise TypeError("snapshot_receipt must be a ReconciliationSnapshotReadReceipt")
            self.snapshot_receipt.verify_snapshot(self.record, self.evidence)
        ids = [item.evidence_id for item in self.evidence]
        kinds = [item.kind for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence identifiers must be unique")
        if len(kinds) != len(set(kinds)):
            raise ValueError("evidence kinds must be unique")
        required = _REQUIRED_EVIDENCE[approval.operation]
        host_completion_required = (
            required - {"provider_operation_inspection"}
        ) | {"host_synchronous_operation_completion"}
        if set(kinds) not in (required, host_completion_required):
            raise ValueError("evidence kinds do not satisfy the resolution policy")
        if set(kinds) == host_completion_required:
            if approval.provider != "docker-local":
                raise ValueError(
                    "Host synchronous completion evidence is restricted to docker-local"
                )
            if (
                next(
                    item for item in self.evidence
                    if item.kind == "host_synchronous_operation_completion"
                ).source
                != "docker-local-host-call-receipts"
            ):
                raise ValueError(
                    "Host synchronous completion evidence must use the configured Local Docker receipt source"
                )
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
