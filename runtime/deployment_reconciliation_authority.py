"""Host-injected two-person approval authority for reconciliation proposals.

No default identity provider exists. A production caller must inject a trusted
HostAuthenticator that verifies a fresh, challenge-bound authentication proof.
This module issues only an in-process, one-use approval capability; it has no
deployment-provider or journal-mutation interface.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Literal, Protocol

from runtime.deployment_reconciliation_audit_store import DurableReconciliationAuditStore
from runtime.deployment_reconciliation_contract import (
    AuthenticatedPrincipal,
    ReconciliationEvidence,
    ReconciliationProposal,
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
    purpose: AuthenticationPurpose
    operation: str
    scope_digest: str
    issued_at: str
    expires_at: str
    requester_subject: str | None = None
    requester_issuer: str | None = None

    def __post_init__(self) -> None:
        for name in ("challenge_id", "nonce", "operation", "scope_digest"):
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


class HostAuthenticator(Protocol):
    """Trusted Host adapter for challenge-bound authentication.

    Implementations must validate the challenge nonce, audience/purpose,
    operation scope, expiry, proof signature/credential and issuer. Returning
    AuthenticatedPrincipal is an assertion by this injected trusted component;
    constructing that data class directly is not authentication.
    """

    def authenticate(
        self,
        challenge: HostAuthenticationChallenge,
        response: object,
    ) -> AuthenticatedPrincipal:
        """Verify a fresh proof and return its immutable principal snapshot."""
        ...


@dataclass(frozen=True)
class ReconciliationCurrentSnapshot:
    """One consistent, freshly read Host snapshot used at approval consumption."""

    record: ReplacementJournalRecord
    evidence: tuple[ReconciliationEvidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.record, ReplacementJournalRecord):
            raise TypeError("snapshot record must be a ReplacementJournalRecord")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, ReconciliationEvidence) for item in self.evidence
        ):
            raise TypeError(
                "snapshot evidence must be a tuple of ReconciliationEvidence"
            )


class ReconciliationSnapshotReader(Protocol):
    """Trusted Host read boundary for current journal and reconciliation evidence.

    Implementations must read the journal and its evidence as one consistent
    snapshot from trusted current sources. They must not accept caller-supplied
    snapshots or silently fall back to stale caches; unavailable, stale, or
    unauthenticated source data must raise an exception. This interface is a
    trust boundary, not an implementation of the underlying storage/provider
    readers.
    """

    def read_current_snapshot(
        self, operation_id: str
    ) -> ReconciliationCurrentSnapshot:
        """Return current immutable journal/evidence state for this operation."""
        ...


@dataclass(frozen=True)
class ReconciliationApprovalGrant:
    """Opaque in-process one-use capability; the token is never logged."""

    proposal: ReconciliationProposal
    proposal_digest: str
    evidence_digest: str
    token: str = field(repr=False)


class ReconciliationApprovalAuthority:
    """Issue and consume exact-scope two-person approvals through a Host IdP.

    The authenticator, trusted issuer allowlist, method allowlist and durable
    audit store are mandatory constructor dependencies. There is intentionally
    no username/password or CLI-string fallback. Grants are held only in this
    process; after restart they cannot be reconstructed and therefore fail
    closed. Consumption records an audit event before returning the approved
    proposal. This class never executes or schedules a reconciliation action.
    """

    def __init__(
        self,
        *,
        authenticator: HostAuthenticator,
        snapshot_reader: ReconciliationSnapshotReader,
        trusted_issuers: frozenset[str],
        trusted_authentication_methods: frozenset[str],
        audit_store: DurableReconciliationAuditStore,
        approval_ttl_seconds: int = 300,
        challenge_ttl_seconds: int = 120,
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
        if not isinstance(audit_store, DurableReconciliationAuditStore):
            raise TypeError("a DurableReconciliationAuditStore is required")
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
        self._authenticator = authenticator
        self._snapshot_reader = snapshot_reader
        self._trusted_issuers = trusted_issuers
        self._trusted_methods = trusted_authentication_methods
        self._audit = audit_store
        self._approval_ttl = approval_ttl_seconds
        self._challenge_ttl = challenge_ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._grants: dict[str, ReconciliationApprovalGrant] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("Host clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

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
        payload = [asdict(item) for item in proposal.evidence]
        return hashlib.sha256(cls._canonical(payload)).hexdigest()

    @classmethod
    def _proposal_digest(
        cls, proposal: ReconciliationProposal, evidence_digest: str
    ) -> str:
        payload = {
            "operation": proposal.approval.operation,
            "record": asdict(proposal.record),
            "evidence_digest": evidence_digest,
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
            principal = self._authenticator.authenticate(challenge, response)
        except Exception as exc:
            raise ReconciliationAuthorizationError(
                f"{challenge.purpose} authentication failed"
            ) from exc
        if not isinstance(principal, AuthenticatedPrincipal):
            raise ReconciliationAuthorizationError(
                "Host authenticator returned an invalid principal snapshot"
            )
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
        record = proposal.record
        if record.phase != "needs_reconciliation":
            raise ReconciliationAuthorizationError(
                "only needs_reconciliation journals can be approved"
            )
        if not record.candidate_runtime_id or not record.previous_runtime_id:
            raise ReconciliationAuthorizationError(
                "both immutable runtime identities are required"
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
        self._record(
            action="reconciliation_approved",
            actor=approver,
            approval_id=approval_id,
            proposal=approved_proposal,
            proposal_digest=proposal_digest,
            evidence_digest=evidence_digest,
        )
        grant = ReconciliationApprovalGrant(
            proposal=approved_proposal,
            proposal_digest=proposal_digest,
            evidence_digest=evidence_digest,
            token=secrets.token_urlsafe(32),
        )
        with self._lock:
            self._grants[grant.token] = grant
        return grant

    def consume(
        self,
        grant: ReconciliationApprovalGrant,
    ) -> ReconciliationProposal:
        """Consume once after reading the exact current Host journal/evidence snapshot.

        The caller cannot supply the "current" record or evidence. The injected
        trusted reader must return one consistent, fresh snapshot; read failures
        fail closed and burn this in-process grant. Consuming the grant does not
        execute a provider action or mutate deployment state.
        """
        if not isinstance(grant, ReconciliationApprovalGrant):
            raise TypeError("grant must be a ReconciliationApprovalGrant")
        with self._lock:
            stored = self._grants.pop(grant.token, None)
        if stored is None or stored != grant:
            raise ReconciliationAuthorizationError(
                "approval grant is unknown, forged, or already consumed"
            )
        now = self._now()
        expires = datetime.fromisoformat(
            grant.proposal.approval.expires_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if now >= expires:
            raise ReconciliationAuthorizationError("reconciliation approval expired")
        try:
            current = self._snapshot_reader.read_current_snapshot(
                grant.proposal.record.operation_id
            )
        except Exception as exc:
            raise ReconciliationAuthorizationError(
                "trusted current journal/evidence snapshot read failed"
            ) from exc
        if not isinstance(current, ReconciliationCurrentSnapshot):
            raise ReconciliationAuthorizationError(
                "trusted snapshot reader returned an invalid snapshot"
            )
        if current.record != grant.proposal.record:
            raise ReconciliationAuthorizationError(
                "journal revision or immutable runtime identity changed after approval"
            )
        evidence_payload = [asdict(item) for item in current.evidence]
        current_evidence_digest = hashlib.sha256(
            self._canonical(evidence_payload)
        ).hexdigest()
        if current_evidence_digest != grant.evidence_digest:
            raise ReconciliationAuthorizationError(
                "reconciliation evidence changed after approval"
            )
        self._record(
            action="reconciliation_approval_consumed",
            actor=grant.proposal.approval.approved_by,
            approval_id=grant.proposal.approval.approval_id,
            proposal=grant.proposal,
            proposal_digest=grant.proposal_digest,
            evidence_digest=grant.evidence_digest,
        )
        return grant.proposal
