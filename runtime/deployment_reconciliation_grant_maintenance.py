"""Operator-only inventory and terminal cleanup for protected approval grants.

This service has no identity provider, proposal issuer, snapshot reader, or
deployment mutation interface. It inspects encrypted grant envelopes against a
complete durable audit chain and only deletes envelopes with proven terminal
audit history. Production callers must expose it only through a trusted local
Host maintenance boundary protected by OS/service ACLs.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from runtime.deployment_reconciliation_audit_store import (
    DurableReconciliationAuditStore,
)
from runtime.deployment_reconciliation_authority import (
    ReconciliationApprovalGrantReference,
)
from runtime.deployment_reconciliation_grant_vault import (
    ReconciliationApprovalGrantVault,
)


class ReconciliationGrantVaultMaintenanceError(RuntimeError):
    """Grant inventory or terminal cleanup could not complete safely."""


@dataclass(frozen=True)
class ReconciliationGrantVaultInventoryItem:
    """Non-secret classification of one authenticated grant envelope."""

    approval_id: str
    operation_id: str
    expires_at: str
    status: Literal[
        "active",
        "claimed",
        "terminal",
        "expired_approved",
        "pending_orphan",
        "expired_orphan",
        "ambiguous",
    ]
    detail: str


@dataclass(frozen=True)
class ReconciliationGrantVaultCleanupReport:
    """Inventory plus the exact envelopes removed or retained."""

    scanned: int
    removed_approval_ids: tuple[str, ...]
    failed_approval_ids: tuple[str, ...]
    retained: tuple[ReconciliationGrantVaultInventoryItem, ...]


class ReconciliationGrantVaultMaintenance:
    """Read-only grant inventory and terminal-only ciphertext cleanup.

    The supplied audit store must be externally anchored in production.
    Its events() method is called before any inspection/deletion and must reject
    an unanchored, unavailable, malformed or forked audit ledger. The vault's
    KMS protector authenticates every envelope before it can be classified.
    """

    def __init__(
        self,
        *,
        audit_store: DurableReconciliationAuditStore,
        grant_vault: ReconciliationApprovalGrantVault,
        clock=None,
    ) -> None:
        if not isinstance(audit_store, DurableReconciliationAuditStore):
            raise TypeError("a DurableReconciliationAuditStore is required")
        if grant_vault is None or any(
            not callable(getattr(grant_vault, method, None))
            for method in ("list_references", "inspect", "delete")
        ):
            raise TypeError(
                "a protected grant vault with list_references, inspect and delete is required"
            )
        self._audit = audit_store
        self._grant_vault = grant_vault
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ReconciliationGrantVaultMaintenanceError(
                "maintenance clock must return a timezone-aware datetime"
            )
        return value.astimezone(timezone.utc)

    def inspect_grant_vault(
        self,
        *,
        _references: tuple[ReconciliationApprovalGrantReference, ...] | None = None,
    ) -> tuple[ReconciliationGrantVaultInventoryItem, ...]:
        """Classify envelopes against the complete verified audit chain.

        A malformed, duplicate, out-of-order or mismatched history is classified
        as ambiguous and is never eligible for cleanup. If the audit store is
        externally anchored, its events() call also verifies exact local/remote
        head equality before any envelope is inspected.
        """
        try:
            events = self._audit.events()
            references = (
                tuple(self._grant_vault.list_references())
                if _references is None
                else tuple(_references)
            )
            if len({item.approval_id for item in references}) != len(references):
                raise ValueError("grant vault contains duplicate approval references")
            inspections = tuple(
                (reference, self._grant_vault.inspect(reference))
                for reference in references
            )
        except Exception as exc:
            raise ReconciliationGrantVaultMaintenanceError(
                "grant inventory could not verify the complete audit chain and protected envelopes"
            ) from exc

        now = self._now()
        inventory: list[ReconciliationGrantVaultInventoryItem] = []
        for reference, inspected in inspections:
            approval_id = inspected.approval_id
            detail = "audit and encrypted grant scope are consistent"
            status: Literal[
                "active",
                "claimed",
                "terminal",
                "expired_approved",
                "pending_orphan",
                "expired_orphan",
                "ambiguous",
            ] = "ambiguous"
            try:
                if reference.approval_id != approval_id:
                    raise ValueError("vault reference approval ID mismatch")
                expires_value = datetime.fromisoformat(
                    inspected.expires_at.replace("Z", "+00:00")
                )
                if expires_value.tzinfo is None or expires_value.utcoffset() is None:
                    raise ValueError("grant expiry has no timezone")
                expired = now >= expires_value.astimezone(timezone.utc)

                related = [item for item in events if item.approval_id == approval_id]
                proposed = [
                    item for item in related
                    if item.action == "reconciliation_proposed"
                ]
                approved = [
                    item for item in related
                    if item.action == "reconciliation_approved"
                ]
                started = [
                    item for item in related
                    if item.action == "reconciliation_approval_consumption_started"
                ]
                consumed = [
                    item for item in related
                    if item.action == "reconciliation_approval_consumed"
                ]
                rejected = [
                    item for item in related
                    if item.action == "reconciliation_rejected"
                ]
                known = proposed + approved + started + consumed + rejected
                if len(known) != len(related):
                    raise ValueError("approval ID has unexpected audit actions")
                if any(
                    len(group) > 1
                    for group in (proposed, approved, started, consumed, rejected)
                ):
                    raise ValueError("approval ID has duplicate audit events")

                scope = {
                    "approval_id": inspected.approval_id,
                    "operation_id": inspected.operation_id,
                    "provider": inspected.provider,
                    "project": inspected.project,
                    "environment": inspected.environment,
                    "journal_phase": inspected.journal_phase,
                    "target_deployment_id": inspected.target_deployment_id,
                    "previous_deployment_id": inspected.previous_deployment_id,
                    "candidate_runtime_id": inspected.candidate_runtime_id,
                    "previous_runtime_id": inspected.previous_runtime_id,
                    "proposal_digest": inspected.proposal_digest,
                    "evidence_digest": inspected.evidence_digest,
                }

                def matches_scope(event) -> bool:
                    return all(
                        getattr(event, name) == value
                        for name, value in scope.items()
                    )

                if approved:
                    if len(proposed) != 1:
                        raise ValueError("approved grant has no unique proposal event")
                    proposal_event, approval_event = proposed[0], approved[0]
                    if (
                        proposal_event.sequence >= approval_event.sequence
                        or not matches_scope(proposal_event)
                        or not matches_scope(approval_event)
                        or proposal_event.actor != inspected.requested_by
                        or approval_event.actor != inspected.approved_by
                        or approval_event.approval_token_digest is None
                        or not secrets.compare_digest(
                            approval_event.approval_token_digest,
                            inspected.token_digest,
                        )
                        or approval_event.approval_expires_at != inspected.expires_at
                    ):
                        raise ValueError("approved event does not match grant payload")

                    terminals = consumed + rejected
                    if started:
                        if (
                            not matches_scope(started[0])
                            or started[0].sequence <= approval_event.sequence
                            or started[0].actor != approval_event.actor
                        ):
                            raise ValueError(
                                "consumption-start event does not match approval"
                            )
                        if not terminals:
                            status = "claimed"
                            detail = (
                                "consumption has started but no terminal event exists; "
                                "retain for incident review"
                            )
                        elif len(terminals) == 1:
                            terminal = terminals[0]
                            if (
                                terminal.sequence <= started[0].sequence
                                or not matches_scope(terminal)
                                or terminal.actor != started[0].actor
                            ):
                                raise ValueError("terminal event does not match claim")
                            status = "terminal"
                            detail = "approval has a verified terminal audit event"
                        else:
                            raise ValueError("approval has multiple terminal events")
                    elif terminals:
                        raise ValueError(
                            "terminal event exists without a consumption claim"
                        )
                    elif expired:
                        status = "expired_approved"
                        detail = (
                            "approved grant expired without a consumption claim; "
                            "retained conservatively"
                        )
                    else:
                        status = "active"
                        detail = "approved grant remains within its TTL"
                else:
                    if started or consumed:
                        raise ValueError("unapproved grant has consumption history")
                    if rejected:
                        if (
                            len(proposed) != 1
                            or rejected[0].sequence <= proposed[0].sequence
                            or not matches_scope(proposed[0])
                            or not matches_scope(rejected[0])
                            or proposed[0].actor != inspected.requested_by
                            or rejected[0].actor != inspected.approved_by
                        ):
                            raise ValueError(
                                "rejected issuance does not match its proposal"
                            )
                        status = "terminal"
                        detail = (
                            "issuance was durably rejected and no approval was issued"
                        )
                    elif proposed:
                        if len(proposed) != 1 or not matches_scope(proposed[0]):
                            raise ValueError(
                                "pending proposal does not match encrypted grant"
                            )
                        status = "expired_orphan" if expired else "pending_orphan"
                        detail = (
                            "expired orphan has no approved audit event"
                            if expired
                            else "grant has no approved audit event yet"
                        )
                    elif not related:
                        status = "expired_orphan" if expired else "pending_orphan"
                        detail = (
                            "expired orphan has no audit history"
                            if expired
                            else "grant has no audit history"
                        )
                    else:
                        raise ValueError(
                            "grant has an ambiguous unapproved audit history"
                        )
            except Exception as exc:
                status = "ambiguous"
                detail = type(exc).__name__

            inventory.append(
                ReconciliationGrantVaultInventoryItem(
                    approval_id=approval_id,
                    operation_id=inspected.operation_id,
                    expires_at=inspected.expires_at,
                    status=status,
                    detail=detail,
                )
            )
        return tuple(inventory)

    def cleanup_terminal_grant_envelopes(
        self,
    ) -> ReconciliationGrantVaultCleanupReport:
        """Retry deletion only for envelopes with a verified terminal audit state.

        Expired approved grants without a claim, claimed-but-unfinished grants,
        pending/orphan grants and ambiguous records are retained. Expiry alone
        never authorizes deletion of an issued approval. This method never
        mutates the audit chain, external checkpoint, journal or runtime state.
        """
        try:
            references = {
                reference.approval_id: reference
                for reference in self._grant_vault.list_references()
            }
            if len(references) != len(tuple(references.values())):
                raise ValueError("grant vault contains duplicate approval references")
            inventory = self.inspect_grant_vault(
                _references=tuple(references.values())
            )
        except Exception as exc:
            raise ReconciliationGrantVaultMaintenanceError(
                "terminal grant cleanup could not build an authenticated inventory"
            ) from exc

        terminal_ids = {
            item.approval_id for item in inventory if item.status == "terminal"
        }
        if not terminal_ids:
            return ReconciliationGrantVaultCleanupReport(
                scanned=len(inventory),
                removed_approval_ids=(),
                failed_approval_ids=(),
                retained=inventory,
            )

        removed: list[str] = []
        failed: list[str] = []
        for approval_id in sorted(terminal_ids):
            reference = references.get(approval_id)
            if reference is None:
                failed.append(approval_id)
                continue
            try:
                self._grant_vault.delete(reference)
                removed.append(approval_id)
            except Exception:
                failed.append(approval_id)

        removed_set = set(removed)
        retained = tuple(
            item for item in inventory if item.approval_id not in removed_set
        )
        return ReconciliationGrantVaultCleanupReport(
            scanned=len(inventory),
            removed_approval_ids=tuple(removed),
            failed_approval_ids=tuple(failed),
            retained=retained,
        )
