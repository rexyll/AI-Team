"""Host-injected two-person approval authority for reconciliation proposals.

No default identity provider exists. A production caller must inject trusted
HostAuthenticator and ReconciliationSnapshotReader implementations. Approval
and consumption claims are fenced by the durable append-only audit ledger; the
bearer capability is returned to the caller and is never persisted in plaintext
by this module. This module has no deployment-provider or journal-mutation API.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from runtime.deployment_reconciliation_audit_store import DurableReconciliationAuditStore
from runtime.deployment_reconciliation_contract import (
    AuthenticatedPrincipal,
    ReconciliationEvidence,
    ReconciliationProposal,
    ReconciliationSnapshotReadReceipt,
    reconciliation_evidence_digest,
    _aware,
)
from runtime.deployment_replacement import ReplacementJournalRecord

AuthenticationPurpose = Literal["requester", "approver"]


class ReconciliationAuthorizationError(PermissionError):
    """A trusted identity or two-person approval check failed."""


@dataclass(frozen=True)
class HostAuthenticationChallenge:
    """Nonce-bound, operation-scoped challenge passed to the trusted IdP adapter."""

    challenge_id: str
    nonce: str = field(repr=False)
    audience: str
    purpose: AuthenticationPurpose
    operation: str
    scope_digest: str
    issued_at: str
    expires_at: str
    requester_subject: str | None = None
    requester_issuer: str | None = None

    def __post_init__(self) -> None:
        for name in ("challenge_id", "nonce", "audience", "operation", "scope_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.purpose not in {"requester", "approver"}:
            raise ValueError("unsupported authentication purpose")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("authentication challenge expiry must follow issuance")
        if self.purpose == "approver" and (
            not self.requester_subject or not self.requester_issuer
        ):
            raise ValueError("approver challenge must identify the requester")


@dataclass(frozen=True)
class VerifiedHostAuthentication:
    """Trusted adapter receipt binding a verified principal to one exact challenge.

    The nonce is represented only by its SHA-256 digest. This receipt is still
    an assertion from the injected Host adapter; constructing it without
    validating the IdP proof does not authenticate a user.
    """

    principal: AuthenticatedPrincipal
    challenge_id: str
    nonce_sha256: str
    audience: str
    purpose: AuthenticationPurpose
    operation: str
    scope_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("verified authentication principal is invalid")
        for name in (
            "challenge_id",
            "nonce_sha256",
            "audience",
            "purpose",
            "operation",
            "scope_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"verified authentication {name} is required")
        if len(self.nonce_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.nonce_sha256
        ):
            raise ValueError("verified authentication nonce_sha256 is invalid")
        if self.purpose not in {"requester", "approver"}:
            raise ValueError("verified authentication purpose is invalid")


class HostAuthenticator(Protocol):
    """Trusted Host adapter for challenge-bound authentication.

    Implementations must validate the IdP proof, nonce, exact audience and
    purpose, operation scope, expiry, signature/credential and issuer, then
    return a receipt carrying those verified challenge bindings. The authority
    independently compares that receipt with the challenge it issued.
    """

    def authenticate(
        self,
        challenge: HostAuthenticationChallenge,
        response: object,
    ) -> VerifiedHostAuthentication:
        """Verify a fresh proof and return its challenge-bound receipt."""
        ...


@dataclass(frozen=True)
class ReconciliationCurrentSnapshot:
    """One consistent, freshly read Host snapshot used at approval consumption."""

    record: ReplacementJournalRecord
    evidence: tuple[ReconciliationEvidence, ...]
    receipt: ReconciliationSnapshotReadReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.record, ReplacementJournalRecord):
            raise TypeError("snapshot record must be a ReplacementJournalRecord")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, ReconciliationEvidence) for item in self.evidence
        ):
            raise TypeError(
                "snapshot evidence must be a tuple of ReconciliationEvidence"
            )
        if not isinstance(self.receipt, ReconciliationSnapshotReadReceipt):
            raise TypeError("snapshot receipt must be a ReconciliationSnapshotReadReceipt")


class ReconciliationSnapshotReader(Protocol):
    """Trusted Host read boundary for current journal and reconciliation evidence.

    Implementations must read journal revision R1, collect authenticated
    provider/router observations, then reread the journal and require revision
    R2 == R1. They return a receipt binding reader identity, operation, journal
    revision, record/evidence digests, the exact evidence source set and read
    start/completion times. This is a journal-revision fence, not a claim that
    independent provider and router APIs share one distributed transaction.
    Implementations must not accept caller-supplied snapshots or fall back to
    stale caches; source authentication failures, revision changes, unavailable
    data and stale observations must raise. The receipt is an assertion from
    the injected trusted reader, not a digital signature.
    """

    def read_current_snapshot(
        self,
        operation_id: str,
        operation: str,
    ) -> ReconciliationCurrentSnapshot:
        """Return current immutable journal/evidence for this exact resolution."""
        ...


_GRANT_APPROVAL_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_GRANT_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReconciliationApprovalGrantReference:
    """Non-secret reference to an externally protected grant envelope."""

    approval_id: str
    envelope_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.approval_id, str) or not _GRANT_APPROVAL_ID.fullmatch(
            self.approval_id
        ):
            raise ValueError("approval_id is malformed")
        if not isinstance(self.envelope_sha256, str) or not _GRANT_SHA256.fullmatch(
            self.envelope_sha256
        ):
            raise ValueError("envelope_sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class ReconciliationApprovalGrant:
    """Opaque one-use bearer capability; only its digest is stored in the audit ledger."""

    proposal: ReconciliationProposal
    proposal_digest: str
    evidence_digest: str
    token: str = field(repr=False)
    storage_reference: ReconciliationApprovalGrantReference | None = field(
        default=None, repr=False, compare=False
    )


class ReconciliationApprovalGrantVault(Protocol):
    """External KMS-backed custody adapter; no software-key fallback is allowed."""

    def save(
        self, grant: ReconciliationApprovalGrant
    ) -> ReconciliationApprovalGrantReference:
        """Durably protect a newly issued grant and return its non-secret reference."""
        ...

    def load(
        self, reference: ReconciliationApprovalGrantReference
    ) -> ReconciliationApprovalGrant:
        """Restore a protected grant without bypassing audit-ledger one-use checks."""
        ...

    def delete(self, reference: ReconciliationApprovalGrantReference) -> None:
        """Delete a grant envelope after terminal handling or failed issuance."""
        ...


class ReconciliationApprovalAuthority:
    """Issue and consume exact-scope two-person approvals through a Host IdP.

    The authenticator, current-snapshot reader, trusted issuer/method allowlists,
    trusted snapshot-reader/evidence-source allowlists, evidence freshness limit
    and durable audit store are mandatory security controls. Approval and
    consumption both obtain current snapshots from the injected reader; a
    receipt supplied by the caller is never treated as source proof. There is
    intentionally no username/password or CLI-string fallback. The audit ledger
    stores only a token digest and fences grant claims across
    processes. When a Host grant vault is injected, the encrypted grant is
    persisted before the approved audit event is appended; the returned grant
    carries a non-secret storage reference for later restoration. Without a
    vault, the caller remains responsible for protecting and retaining the
    bearer capability. A started-but-unfinished claim is terminal and requires
    a fresh dual approval. This class never executes or schedules a
    reconciliation action.
    """

    def __init__(
        self,
        *,
        authenticator: HostAuthenticator,
        snapshot_reader: ReconciliationSnapshotReader,
        trusted_issuers: frozenset[str],
        trusted_authentication_methods: frozenset[str],
        trusted_snapshot_readers: frozenset[str],
        trusted_evidence_sources: frozenset[str],
        authentication_audience: str,
        audit_store: DurableReconciliationAuditStore,
        approval_ttl_seconds: int = 300,
        challenge_ttl_seconds: int = 120,
        evidence_max_age_seconds: int = 300,
        snapshot_read_max_duration_seconds: int = 60,
        grant_vault: ReconciliationApprovalGrantVault | None = None,
        clock=None,
    ) -> None:
        if authenticator is None or not callable(
            getattr(authenticator, "authenticate", None)
        ):
            raise TypeError("a trusted HostAuthenticator is required")
        if snapshot_reader is None or not callable(
            getattr(snapshot_reader, "read_current_snapshot", None)
        ):
            raise TypeError("a trusted ReconciliationSnapshotReader is required")
        if not isinstance(trusted_issuers, frozenset) or not trusted_issuers or any(
            not isinstance(item, str) or not item.strip()
            for item in trusted_issuers
        ):
            raise ValueError("trusted_issuers must be a non-empty frozenset")
        if (
            not isinstance(trusted_authentication_methods, frozenset)
            or not trusted_authentication_methods
            or any(
                not isinstance(item, str) or not item.strip()
                for item in trusted_authentication_methods
            )
        ):
            raise ValueError(
                "trusted_authentication_methods must be a non-empty frozenset"
            )
        for name, values in (
            ("trusted_snapshot_readers", trusted_snapshot_readers),
            ("trusted_evidence_sources", trusted_evidence_sources),
        ):
            if not isinstance(values, frozenset) or not values or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise ValueError(f"{name} must be a non-empty frozenset")
        if (
            not isinstance(authentication_audience, str)
            or not authentication_audience.strip()
        ):
            raise ValueError("authentication_audience must be a non-empty string")
        if not isinstance(audit_store, DurableReconciliationAuditStore):
            raise TypeError("a DurableReconciliationAuditStore is required")
        if grant_vault is not None and any(
            not callable(getattr(grant_vault, method, None))
            for method in ("save", "load", "delete")
        ):
            raise TypeError(
                "grant_vault must provide durable save, load and delete methods"
            )
        if (
            not isinstance(approval_ttl_seconds, int)
            or isinstance(approval_ttl_seconds, bool)
            or not 1 <= approval_ttl_seconds <= 900
        ):
            raise ValueError("approval_ttl_seconds must be between 1 and 900")
        if (
            not isinstance(challenge_ttl_seconds, int)
            or isinstance(challenge_ttl_seconds, bool)
            or not 15 <= challenge_ttl_seconds <= 300
        ):
            raise ValueError("challenge_ttl_seconds must be between 15 and 300")
        if (
            not isinstance(evidence_max_age_seconds, int)
            or isinstance(evidence_max_age_seconds, bool)
            or not 1 <= evidence_max_age_seconds <= 3600
        ):
            raise ValueError("evidence_max_age_seconds must be between 1 and 3600")
        if (
            not isinstance(snapshot_read_max_duration_seconds, int)
            or isinstance(snapshot_read_max_duration_seconds, bool)
            or not 1 <= snapshot_read_max_duration_seconds <= 300
        ):
            raise ValueError("snapshot_read_max_duration_seconds must be between 1 and 300")
        self._authenticator = authenticator
        self._snapshot_reader = snapshot_reader
        self._trusted_issuers = trusted_issuers
        self._trusted_methods = trusted_authentication_methods
        self._trusted_snapshot_readers = trusted_snapshot_readers
        self._trusted_evidence_sources = trusted_evidence_sources
        self._authentication_audience = authentication_audience
        self._audit = audit_store
        self._grant_vault = grant_vault
        self._approval_ttl = approval_ttl_seconds
        self._challenge_ttl = challenge_ttl_seconds
        self._evidence_max_age = timedelta(seconds=evidence_max_age_seconds)
        self._snapshot_read_max_duration = timedelta(
            seconds=snapshot_read_max_duration_seconds
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("Host clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _validate_evidence_freshness(
        self,
        evidence: tuple[ReconciliationEvidence, ...],
        *,
        now: datetime,
    ) -> None:
        if not isinstance(evidence, tuple) or not evidence:
            raise ReconciliationAuthorizationError(
                "reconciliation evidence is missing"
            )
        for item in evidence:
            if not isinstance(item, ReconciliationEvidence):
                raise ReconciliationAuthorizationError(
                    "reconciliation evidence contains an invalid item"
                )
            observed_at = datetime.fromisoformat(
                item.observed_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            age = now - observed_at
            if age < timedelta(0):
                raise ReconciliationAuthorizationError(
                    "reconciliation evidence is future-dated"
                )
            if age > self._evidence_max_age:
                raise ReconciliationAuthorizationError(
                    f"reconciliation evidence is stale: {item.kind}"
                )

    def _validate_snapshot_receipt(
        self,
        receipt: ReconciliationSnapshotReadReceipt,
        record: ReplacementJournalRecord,
        evidence: tuple[ReconciliationEvidence, ...],
        *,
        now: datetime,
    ) -> str:
        if not isinstance(receipt, ReconciliationSnapshotReadReceipt):
            raise ReconciliationAuthorizationError(
                "trusted snapshot reader did not provide a provenance receipt"
            )
        if receipt.reader_id not in self._trusted_snapshot_readers:
            raise ReconciliationAuthorizationError(
                "snapshot reader identity is not trusted"
            )
        unexpected_sources = set(receipt.evidence_sources) - self._trusted_evidence_sources
        if unexpected_sources:
            raise ReconciliationAuthorizationError(
                "snapshot contains evidence from an untrusted source"
            )
        try:
            receipt.verify_snapshot(record, evidence)
        except (TypeError, ValueError) as exc:
            raise ReconciliationAuthorizationError(
                "snapshot provenance receipt does not bind the supplied journal/evidence"
            ) from exc
        started = datetime.fromisoformat(
            receipt.read_started_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        completed = datetime.fromisoformat(
            receipt.read_completed_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if completed > now:
            raise ReconciliationAuthorizationError(
                "snapshot read receipt is future-dated"
            )
        if now - completed > self._evidence_max_age:
            raise ReconciliationAuthorizationError(
                "snapshot read receipt is stale"
            )
        for item in evidence:
            observed_at = datetime.fromisoformat(
                item.observed_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if observed_at > completed:
                raise ReconciliationAuthorizationError(
                    "snapshot read receipt completed before an evidence observation"
                )
        if completed - started > self._snapshot_read_max_duration:
            raise ReconciliationAuthorizationError(
                "snapshot read exceeded the configured consistency window"
            )
        return receipt.approval_binding_digest()

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _canonical(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def _evidence_digest(cls, proposal: ReconciliationProposal) -> str:
        return reconciliation_evidence_digest(proposal.evidence)

    @classmethod
    def _proposal_digest(
        cls, proposal: ReconciliationProposal, evidence_digest: str
    ) -> str:
        if proposal.snapshot_receipt is None:
            raise ReconciliationAuthorizationError(
                "proposal has no trusted snapshot provenance receipt"
            )
        payload = {
            "operation": proposal.approval.operation,
            "record": asdict(proposal.record),
            "evidence_digest": evidence_digest,
            "snapshot_provenance_digest": proposal.snapshot_receipt.approval_binding_digest(),
        }
        return hashlib.sha256(cls._canonical(payload)).hexdigest()

    def _challenge(
        self,
        *,
        purpose: AuthenticationPurpose,
        operation: str,
        scope_digest: str,
        now: datetime,
        requester: AuthenticatedPrincipal | None = None,
    ) -> HostAuthenticationChallenge:
        return HostAuthenticationChallenge(
            challenge_id=secrets.token_urlsafe(24),
            nonce=secrets.token_urlsafe(32),
            audience=self._authentication_audience,
            purpose=purpose,
            operation=operation,
            scope_digest=scope_digest,
            issued_at=self._iso(now),
            expires_at=self._iso(now + timedelta(seconds=self._challenge_ttl)),
            requester_subject=requester.subject if requester else None,
            requester_issuer=requester.issuer if requester else None,
        )

    def _authenticate(
        self,
        challenge: HostAuthenticationChallenge,
        response: object,
    ) -> AuthenticatedPrincipal:
        if response is None:
            raise ReconciliationAuthorizationError(
                f"{challenge.purpose} authentication proof is required"
            )
        try:
            receipt = self._authenticator.authenticate(challenge, response)
        except Exception as exc:
            raise ReconciliationAuthorizationError(
                f"{challenge.purpose} authentication failed"
            ) from exc
        if not isinstance(receipt, VerifiedHostAuthentication):
            raise ReconciliationAuthorizationError(
                "Host authenticator returned an invalid challenge-binding receipt"
            )
        expected_nonce_digest = hashlib.sha256(
            challenge.nonce.encode("utf-8")
        ).hexdigest()
        if (
            receipt.challenge_id != challenge.challenge_id
            or not secrets.compare_digest(
                receipt.nonce_sha256, expected_nonce_digest
            )
            or receipt.audience != challenge.audience
            or receipt.purpose != challenge.purpose
            or receipt.operation != challenge.operation
            or receipt.scope_digest != challenge.scope_digest
        ):
            raise ReconciliationAuthorizationError(
                "Host authentication receipt does not match the issued challenge"
            )
        principal = receipt.principal
        if principal.issuer not in self._trusted_issuers:
            raise ReconciliationAuthorizationError(
                "authenticated principal issuer is not trusted"
            )
        if principal.authentication_method not in self._trusted_methods:
            raise ReconciliationAuthorizationError(
                "authenticated principal method is not trusted"
            )
        now = self._now()
        authenticated_at = datetime.fromisoformat(
            principal.authenticated_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        challenge_issued = datetime.fromisoformat(
            challenge.issued_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        challenge_expires = datetime.fromisoformat(
            challenge.expires_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if now >= challenge_expires:
            raise ReconciliationAuthorizationError(
                f"{challenge.purpose} authentication challenge expired"
            )
        if authenticated_at < challenge_issued or authenticated_at > now:
            raise ReconciliationAuthorizationError(
                "authenticated principal timestamp is outside the challenge window"
            )
        return principal

    def _record(
        self,
        *,
        action: str,
        actor: AuthenticatedPrincipal,
        approval_id: str,
        proposal: ReconciliationProposal,
        proposal_digest: str,
        evidence_digest: str,
        approval_token_digest: str | None = None,
        approval_expires_at: str | None = None,
    ) -> None:
        record = proposal.record
        if record.candidate_runtime_id is None or record.previous_runtime_id is None:
            raise ReconciliationAuthorizationError(
                "both immutable runtime identities are required for audit"
            )
        self._audit.record(
            action=action,
            actor=actor,
            approval_id=approval_id,
            operation_id=record.operation_id,
            provider=record.provider,
            project=record.project,
            environment=record.environment,
            journal_phase=record.phase,
            target_deployment_id=record.target_deployment_id,
            previous_deployment_id=record.previous_deployment_id,
            candidate_runtime_id=record.candidate_runtime_id,
            previous_runtime_id=record.previous_runtime_id,
            proposal_digest=proposal_digest,
            evidence_digest=evidence_digest,
            recorded_at=self._iso(self._now()),
            approval_token_digest=approval_token_digest,
            approval_expires_at=approval_expires_at,
        )

    def authorize_proposal(
        self,
        proposal: ReconciliationProposal,
        *,
        requester_response: object,
        approver_response: object,
    ) -> ReconciliationApprovalGrant:
        """Authenticate two distinct humans and issue a short-lived approval.

        Principal fields supplied in the proposal's data-only approval template
        are not trusted. They are overwritten with identities returned by the
        injected authenticator after challenge verification.
        """
        if not isinstance(proposal, ReconciliationProposal):
            raise TypeError("proposal must be a ReconciliationProposal")
        # Caller evidence is proposal-time context only. Freshness is checked
        # against the trusted reader's current evidence below, not against
        # potentially stale caller-supplied observations.
        record = proposal.record
        if record.phase != "needs_reconciliation":
            raise ReconciliationAuthorizationError(
                "only needs_reconciliation journals can be approved"
            )
        if not record.candidate_runtime_id or not record.previous_runtime_id:
            raise ReconciliationAuthorizationError(
                "both immutable runtime identities are required"
            )

        # Never trust a receipt supplied with the proposal. Obtain a fresh,
        # authoritative snapshot from the injected Host reader before starting
        # either authentication challenge.
        try:
            current = self._snapshot_reader.read_current_snapshot(
                record.operation_id, proposal.approval.operation
            )
        except Exception as exc:
            raise ReconciliationAuthorizationError(
                "trusted current journal/evidence snapshot read failed before approval"
            ) from exc
        if not isinstance(current, ReconciliationCurrentSnapshot):
            raise ReconciliationAuthorizationError(
                "trusted snapshot reader returned an invalid snapshot"
            )
        if current.record != record:
            raise ReconciliationAuthorizationError(
                "proposal journal revision or immutable runtime identity is not current"
            )
        # The caller's evidence is only a proposal-time hint. Repeated live
        # reads naturally have different observation timestamps and generated
        # evidence IDs, so bind the approval to the fresh Host-reader result.
        # The proposal's operation/journal scope remains exact, and the
        # trusted reader must provide the complete operation-specific evidence.
        trusted_read_at = self._now()
        self._validate_evidence_freshness(
            current.evidence,
            now=trusted_read_at,
        )
        self._validate_snapshot_receipt(
            current.receipt,
            current.record,
            current.evidence,
            now=trusted_read_at,
        )
        proposal = replace(
            proposal,
            evidence=current.evidence,
            snapshot_receipt=current.receipt,
        )
        evidence_digest = self._evidence_digest(proposal)
        proposal_digest = self._proposal_digest(proposal, evidence_digest)
        approval_id = secrets.token_urlsafe(24)

        requester_challenge = self._challenge(
            purpose="requester",
            operation=proposal.approval.operation,
            scope_digest=proposal_digest,
            now=self._now(),
        )
        requester = self._authenticate(requester_challenge, requester_response)
        self._record(
            action="reconciliation_proposed",
            actor=requester,
            approval_id=approval_id,
            proposal=proposal,
            proposal_digest=proposal_digest,
            evidence_digest=evidence_digest,
        )

        approver_challenge = self._challenge(
            purpose="approver",
            operation=proposal.approval.operation,
            scope_digest=proposal_digest,
            now=self._now(),
            requester=requester,
        )
        approver = self._authenticate(approver_challenge, approver_response)
        if (requester.issuer, requester.subject) == (
            approver.issuer,
            approver.subject,
        ):
            self._record(
                action="reconciliation_rejected",
                actor=approver,
                approval_id=approval_id,
                proposal=proposal,
                proposal_digest=proposal_digest,
                evidence_digest=evidence_digest,
            )
            raise ReconciliationAuthorizationError(
                "requester and approver must be distinct authenticated principals"
            )

        issued_at = self._now()
        try:
            self._validate_evidence_freshness(proposal.evidence, now=issued_at)
        except ReconciliationAuthorizationError:
            self._record(
                action="reconciliation_rejected",
                actor=approver,
                approval_id=approval_id,
                proposal=proposal,
                proposal_digest=proposal_digest,
                evidence_digest=evidence_digest,
            )
            raise
        approval = replace(
            proposal.approval,
            approval_id=approval_id,
            requested_by=requester,
            approved_by=approver,
            issued_at=self._iso(issued_at),
            expires_at=self._iso(
                issued_at + timedelta(seconds=self._approval_ttl)
            ),
        )
        approved_proposal = replace(proposal, approval=approval)
        grant = ReconciliationApprovalGrant(
            proposal=approved_proposal,
            proposal_digest=proposal_digest,
            evidence_digest=evidence_digest,
            token=secrets.token_urlsafe(32),
        )
        storage_reference = None
        if self._grant_vault is not None:
            try:
                storage_reference = self._grant_vault.save(grant)
                if not isinstance(
                    storage_reference, ReconciliationApprovalGrantReference
                ):
                    raise TypeError(
                        "grant vault returned an invalid storage reference"
                    )
                if storage_reference.approval_id != approval_id:
                    raise ValueError(
                        "grant vault reference does not match the issued approval ID"
                    )
                expires = datetime.fromisoformat(
                    approval.expires_at.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                if self._now() >= expires:
                    raise ReconciliationAuthorizationError(
                        "approval expired while the protected grant was being stored"
                    )
            except Exception as exc:
                if (
                    storage_reference is not None
                    and storage_reference.approval_id == approval_id
                ):
                    try:
                        self._grant_vault.delete(storage_reference)
                    except Exception:
                        # An unapproved orphaned ciphertext cannot be consumed;
                        # its expiry bounds retention if cleanup is unavailable.
                        pass
                self._record(
                    action="reconciliation_rejected",
                    actor=approver,
                    approval_id=approval_id,
                    proposal=approved_proposal,
                    proposal_digest=proposal_digest,
                    evidence_digest=evidence_digest,
                )
                raise ReconciliationAuthorizationError(
                    "approved grant could not be durably protected"
                ) from exc

        token_digest = hashlib.sha256(grant.token.encode("utf-8")).hexdigest()
        try:
            self._record(
                action="reconciliation_approved",
                actor=approver,
                approval_id=approval_id,
                proposal=approved_proposal,
                proposal_digest=proposal_digest,
                evidence_digest=evidence_digest,
                approval_token_digest=token_digest,
                approval_expires_at=approval.expires_at,
            )
        except Exception as exc:
            if storage_reference is not None:
                try:
                    self._grant_vault.delete(storage_reference)
                except Exception:
                    # The orphaned ciphertext has no approved audit event and
                    # cannot be consumed; it expires and can be swept later.
                    pass
            raise ReconciliationAuthorizationError(
                "approval could not be durably recorded"
            ) from exc
        return replace(grant, storage_reference=storage_reference)

    def consume(
        self,
        grant: ReconciliationApprovalGrant,
    ) -> ReconciliationProposal:
        """Consume a durable one-use grant after a fresh Host snapshot read.

        The bearer token is represented in the audit chain only by its SHA-256
        digest. A caller may restore a grant object after a Host restart; the
        append-only audit ledger, not process memory, is the source of truth.
        A durable consumption-start event fences every later attempt. If the
        process crashes while checking the read-only snapshot, the grant remains
        claimed and must be re-approved rather than replayed.
        """
        if not isinstance(grant, ReconciliationApprovalGrant):
            raise TypeError("grant must be a ReconciliationApprovalGrant")
        if not isinstance(grant.token, str) or not grant.token:
            raise ReconciliationAuthorizationError(
                "approval grant is unknown or forged"
            )
        proposal = grant.proposal
        if not isinstance(proposal, ReconciliationProposal):
            raise ReconciliationAuthorizationError(
                "approval grant is unknown or forged"
            )
        calculated_evidence_digest = self._evidence_digest(proposal)
        calculated_proposal_digest = self._proposal_digest(
            proposal, calculated_evidence_digest
        )
        if (
            not secrets.compare_digest(
                calculated_evidence_digest, grant.evidence_digest
            )
            or not secrets.compare_digest(
                calculated_proposal_digest, grant.proposal_digest
            )
        ):
            raise ReconciliationAuthorizationError(
                "approval grant is unknown or does not match its approved proposal"
            )

        approval = proposal.approval
        token_digest = hashlib.sha256(grant.token.encode("utf-8")).hexdigest()
        try:
            self._audit.begin_approval_consumption(
                approval_id=approval.approval_id,
                token_digest=token_digest,
                proposal_digest=grant.proposal_digest,
                evidence_digest=grant.evidence_digest,
                approval_expires_at=approval.expires_at,
                requester=approval.requested_by,
                approver=approval.approved_by,
                recorded_at=self._iso(self._now()),
            )
        except Exception as exc:
            raise ReconciliationAuthorizationError(
                "approval grant is unknown, forged, already claimed, or already consumed"
            ) from exc

        def reject_claim() -> None:
            self._audit.finish_approval_consumption(
                approval_id=approval.approval_id,
                proposal_digest=grant.proposal_digest,
                evidence_digest=grant.evidence_digest,
                action="reconciliation_rejected",
                recorded_at=self._iso(self._now()),
            )

        try:
            expires = datetime.fromisoformat(
                approval.expires_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if self._now() >= expires:
                raise ReconciliationAuthorizationError(
                    "reconciliation approval expired"
                )
            try:
                current = self._snapshot_reader.read_current_snapshot(
                    proposal.record.operation_id, approval.operation
                )
            except Exception as exc:
                raise ReconciliationAuthorizationError(
                    "trusted current journal/evidence snapshot read failed"
                ) from exc
            if not isinstance(current, ReconciliationCurrentSnapshot):
                raise ReconciliationAuthorizationError(
                    "trusted snapshot reader returned an invalid snapshot"
                )
            if current.record != proposal.record:
                raise ReconciliationAuthorizationError(
                    "journal revision or immutable runtime identity changed after approval"
                )
            current_evidence_digest = reconciliation_evidence_digest(
                current.evidence
            )
            if current_evidence_digest != grant.evidence_digest:
                raise ReconciliationAuthorizationError(
                    "reconciliation evidence changed after approval"
                )
            now_after_snapshot = self._now()
            self._validate_evidence_freshness(
                current.evidence, now=now_after_snapshot
            )
            current_binding = self._validate_snapshot_receipt(
                current.receipt,
                current.record,
                current.evidence,
                now=now_after_snapshot,
            )
            approved_receipt = proposal.snapshot_receipt
            if approved_receipt is None or current_binding != approved_receipt.approval_binding_digest():
                raise ReconciliationAuthorizationError(
                    "snapshot reader, journal revision, or evidence provenance changed after approval"
                )
            if now_after_snapshot >= expires:
                raise ReconciliationAuthorizationError(
                    "reconciliation approval expired"
                )
            self._audit.finish_approval_consumption(
                approval_id=approval.approval_id,
                proposal_digest=grant.proposal_digest,
                evidence_digest=grant.evidence_digest,
                action="reconciliation_approval_consumed",
                recorded_at=self._iso(self._now()),
            )
            return proposal
        except ReconciliationAuthorizationError:
            try:
                reject_claim()
            except Exception as audit_exc:
                raise ReconciliationAuthorizationError(
                    "approval validation failed and its rejection could not be finalized; "
                    "the durable consumption claim remains fail-closed"
                ) from audit_exc
            raise
        except Exception as exc:
            try:
                reject_claim()
            except Exception as audit_exc:
                raise ReconciliationAuthorizationError(
                    "approval consumption failed and its rejection could not be finalized; "
                    "the durable consumption claim remains fail-closed"
                ) from audit_exc
            raise ReconciliationAuthorizationError(
                "approval consumption failed closed"
            ) from exc
