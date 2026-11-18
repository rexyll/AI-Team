"""Durable append-only persistence for deployment reconciliation audit envelopes.

The hash chain detects edits/reordering only while the current head is compared
with a checkpoint kept outside this writable directory. This store does not
authenticate principals, issue/consume approvals, or execute reconciliation
mutations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from runtime.deployment_reconciliation_audit import (
    AuditAction,
    ReconciliationAuditEnvelope,
    _ZERO_DIGEST,
)
from runtime.deployment_reconciliation_contract import AuthenticatedPrincipal
from runtime.process_lock import exclusive_process_lock

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReconciliationAuditIntegrityError(RuntimeError):
    """The persisted reconciliation audit chain is malformed or inconsistent."""


@dataclass(frozen=True)
class ReconciliationAuditHead:
    """Checkpoint intended to be exported to an external trusted store."""

    sequence: int
    event_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ValueError("sequence must be a non-negative integer")
        if not isinstance(self.event_digest, str) or not _SHA256.fullmatch(
            self.event_digest
        ):
            raise ValueError("event_digest must be a lowercase SHA-256 digest")
        if self.sequence == 0 and self.event_digest != _ZERO_DIGEST:
            raise ValueError("the empty audit head must use the zero digest")
        if self.sequence > 0 and self.event_digest == _ZERO_DIGEST:
            raise ValueError("a non-empty audit head must have a non-zero digest")


class DurableReconciliationAuditStore:
    """Process-safe JSONL audit ledger with full hash-chain verification.

    The public API supports append, read, and verify only. It has no update,
    delete, truncate, or rewrite method. On POSIX, the directory is restricted
    to mode 0700 and event/lock files to 0600. A local hash chain is not a
    substitute for a trusted head checkpoint retained outside this directory.
    """

    FILE_NAME = "deployment-reconciliation-audit.jsonl"
    LOCK_NAME = ".deployment-reconciliation-audit.lock"

    def __init__(self, root: str | Path) -> None:
        if not isinstance(root, (str, Path)) or not str(root).strip():
            raise ValueError("root must be a non-empty path")
        supplied_root = Path(root).expanduser()
        supplied_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if supplied_root.is_symlink() or not supplied_root.is_dir():
            raise ValueError("audit root must be a real directory, not a symlink")
        self.root = supplied_root.resolve()
        self.path = self.root / self.FILE_NAME
        self.lock_path = self.root / self.LOCK_NAME
        self._lock = RLock()
        self._validate_paths()
        if os.name == "posix":
            os.chmod(self.root, 0o700)
            if self.path.exists():
                os.chmod(self.path, 0o600)
            if self.lock_path.exists():
                os.chmod(self.lock_path, 0o600)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _validate_paths(self) -> None:
        if self.root.is_symlink() or not self.root.is_dir():
            raise ReconciliationAuditIntegrityError(
                "audit root is not a trusted directory"
            )
        for path in (self.path, self.lock_path):
            if path.is_symlink():
                raise ReconciliationAuditIntegrityError(
                    f"audit path must not be a symlink: {path.name}"
                )
            if path.exists():
                try:
                    metadata = path.stat(follow_symlinks=False)
                except OSError as exc:
                    raise ReconciliationAuditIntegrityError(
                        f"could not inspect audit path {path.name}"
                    ) from exc
                if not stat.S_ISREG(metadata.st_mode):
                    raise ReconciliationAuditIntegrityError(
                        f"audit path must be a regular file: {path.name}"
                    )
                if os.name == "posix" and metadata.st_nlink != 1:
                    raise ReconciliationAuditIntegrityError(
                        f"audit path must not have additional hard links: {path.name}"
                    )

    @staticmethod
    def _build_event(
        *,
        sequence: int,
        previous_digest: str,
        action: AuditAction,
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
    ) -> ReconciliationAuditEnvelope:
        values = {
            "event_id": uuid4().hex,
            "sequence": sequence,
            "previous_digest": previous_digest,
            "action": action,
            "actor": actor,
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
            "approval_token_digest": approval_token_digest,
            "approval_expires_at": approval_expires_at,
        }
        provisional = ReconciliationAuditEnvelope.__new__(
            ReconciliationAuditEnvelope
        )
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        digest = hashlib.sha256(provisional.canonical_payload()).hexdigest()
        return ReconciliationAuditEnvelope(**values, event_digest=digest)

    def _read_unlocked(self) -> tuple[ReconciliationAuditEnvelope, ...]:
        self._validate_paths()
        if not self.path.exists():
            return ()
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ReconciliationAuditIntegrityError(
                f"could not read reconciliation audit ledger: {type(exc).__name__}"
            ) from exc

        events: list[ReconciliationAuditEnvelope] = []
        event_ids: set[str] = set()
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                raise ReconciliationAuditIntegrityError(
                    f"blank line in reconciliation audit ledger at line {line_number}"
                )
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("event payload must be an object")
                actor_payload = payload.pop("actor", None)
                if not isinstance(actor_payload, dict):
                    raise ValueError("actor snapshot is missing or malformed")
                event = ReconciliationAuditEnvelope(
                    actor=AuthenticatedPrincipal(**actor_payload),
                    **payload,
                )
                if event.event_id in event_ids:
                    raise ValueError("duplicate audit event identifier")
                if events:
                    event.verify_successor_of(events[-1])
                elif event.sequence != 1 or event.previous_digest != _ZERO_DIGEST:
                    raise ValueError("first audit event must start at sequence 1")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ReconciliationAuditIntegrityError(
                    f"invalid reconciliation audit event at line {line_number}: {str(exc)[:300]}"
                ) from exc
            event_ids.add(event.event_id)
            events.append(event)
        return tuple(events)

    def _append_unlocked(
        self,
        event: ReconciliationAuditEnvelope,
        events: tuple[ReconciliationAuditEnvelope, ...],
    ) -> None:
        if not isinstance(event, ReconciliationAuditEnvelope):
            raise TypeError("event must be a ReconciliationAuditEnvelope")
        self._validate_paths()
        if any(item.event_id == event.event_id for item in events):
            raise ValueError("audit event identifier already exists")
        expected_sequence = len(events) + 1
        expected_previous = events[-1].event_digest if events else _ZERO_DIGEST
        if event.sequence != expected_sequence or event.previous_digest != expected_previous:
            raise ValueError("audit event does not extend the current ledger head")
        if events:
            event.verify_successor_of(events[-1])
        elif event.sequence != 1 or event.previous_digest != _ZERO_DIGEST:
            raise ValueError("first audit event must start at sequence 1")

        serialized = json.dumps(
            asdict(event),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        created = not self.path.exists()
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            try:
                descriptor = os.open(self.path, flags | os.O_EXCL, 0o600)
            except FileExistsError:
                descriptor = os.open(self.path, flags, 0o600)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                os.close(descriptor)
                raise ReconciliationAuditIntegrityError(
                    "audit event path is not a regular file"
                )
            if os.name == "posix" and metadata.st_nlink != 1:
                os.close(descriptor)
                raise ReconciliationAuditIntegrityError(
                    "audit event file must not have additional hard links"
                )
            with os.fdopen(
                descriptor, "a", encoding="utf-8", newline="\n"
            ) as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "posix":
                os.chmod(self.path, 0o600)
                os.chmod(self.root, 0o700)
                if created:
                    directory_fd = os.open(
                        self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                    )
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
        except (OSError, UnicodeError) as exc:
            raise ReconciliationAuditIntegrityError(
                f"could not append reconciliation audit event: {type(exc).__name__}"
            ) from exc

    def append(self, event: ReconciliationAuditEnvelope) -> ReconciliationAuditEnvelope:
        """Append a pre-built event only if it is the exact next chain entry."""
        with exclusive_process_lock(self.lock_path), self._lock:
            if os.name == "posix" and self.lock_path.exists():
                os.chmod(self.lock_path, 0o600)
            events = self._read_unlocked()
            self._append_unlocked(event, events)
            return event

    def record(
        self,
        *,
        action: AuditAction,
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
        recorded_at: str | None = None,
        approval_token_digest: str | None = None,
        approval_expires_at: str | None = None,
    ) -> ReconciliationAuditEnvelope:
        """Create and append an event using the current trusted local chain head.

        The actor snapshot must be supplied by a future trusted Host authenticator.
        Constructing AuthenticatedPrincipal is not itself authentication.
        """
        if not isinstance(actor, AuthenticatedPrincipal):
            raise TypeError("actor must be an AuthenticatedPrincipal")
        with exclusive_process_lock(self.lock_path), self._lock:
            if os.name == "posix" and self.lock_path.exists():
                os.chmod(self.lock_path, 0o600)
            events = self._read_unlocked()
            event = self._build_event(
                sequence=len(events) + 1,
                previous_digest=events[-1].event_digest if events else _ZERO_DIGEST,
                action=action,
                actor=actor,
                approval_id=approval_id,
                operation_id=operation_id,
                provider=provider,
                project=project,
                environment=environment,
                journal_phase=journal_phase,
                target_deployment_id=target_deployment_id,
                previous_deployment_id=previous_deployment_id,
                candidate_runtime_id=candidate_runtime_id,
                previous_runtime_id=previous_runtime_id,
                proposal_digest=proposal_digest,
                evidence_digest=evidence_digest,
                recorded_at=recorded_at or self._now(),
                approval_token_digest=approval_token_digest,
                approval_expires_at=approval_expires_at,
            )
            self._append_unlocked(event, events)
            return event


    @staticmethod
    def _approval_scope_matches(
        left: ReconciliationAuditEnvelope,
        right: ReconciliationAuditEnvelope,
    ) -> bool:
        fields = (
            "approval_id",
            "operation_id",
            "provider",
            "project",
            "environment",
            "journal_phase",
            "target_deployment_id",
            "previous_deployment_id",
            "candidate_runtime_id",
            "previous_runtime_id",
            "proposal_digest",
            "evidence_digest",
        )
        return all(getattr(left, name) == getattr(right, name) for name in fields)

    def begin_approval_consumption(
        self,
        *,
        approval_id: str,
        token_digest: str,
        proposal_digest: str,
        evidence_digest: str,
        approval_expires_at: str,
        requester: AuthenticatedPrincipal,
        approver: AuthenticatedPrincipal,
        recorded_at: str | None = None,
    ) -> ReconciliationAuditEnvelope:
        """Atomically claim a durable one-use grant across threads/processes.

        The bearer token is never persisted: only its SHA-256 digest is checked
        against the approval event. A started claim is terminal for reuse even
        if the process crashes before snapshot verification completes.
        """
        if not isinstance(token_digest, str) or not _SHA256.fullmatch(token_digest):
            raise ValueError("token_digest must be a lowercase SHA-256 digest")
        if not isinstance(requester, AuthenticatedPrincipal):
            raise TypeError("requester must be an AuthenticatedPrincipal")
        if not isinstance(approver, AuthenticatedPrincipal):
            raise TypeError("approver must be an AuthenticatedPrincipal")
        with exclusive_process_lock(self.lock_path), self._lock:
            if os.name == "posix" and self.lock_path.exists():
                os.chmod(self.lock_path, 0o600)
            events = self._read_unlocked()
            approvals = [
                item for item in events
                if item.action == "reconciliation_approved"
                and item.approval_id == approval_id
            ]
            proposals = [
                item for item in events
                if item.action == "reconciliation_proposed"
                and item.approval_id == approval_id
            ]
            if len(approvals) != 1 or len(proposals) != 1:
                raise ReconciliationAuditIntegrityError(
                    "approval grant is unknown or has an invalid audit history"
                )
            approved, proposed = approvals[0], proposals[0]
            if (
                approved.approval_token_digest is None
                or approved.approval_expires_at is None
                or not secrets.compare_digest(
                    approved.approval_token_digest, token_digest
                )
                or approved.approval_expires_at != approval_expires_at
                or approved.proposal_digest != proposal_digest
                or approved.evidence_digest != evidence_digest
                or approved.actor != approver
                or proposed.actor != requester
                or not self._approval_scope_matches(approved, proposed)
            ):
                raise ReconciliationAuditIntegrityError(
                    "approval grant is forged or does not match its durable approval"
                )
            attempts = [
                item for item in events
                if item.approval_id == approval_id
                and item.action in {
                    "reconciliation_approval_consumption_started",
                    "reconciliation_approval_consumed",
                    "reconciliation_rejected",
                }
            ]
            if attempts:
                raise ReconciliationAuditIntegrityError(
                    "approval grant is unknown, already claimed, or already consumed"
                )
            event = self._build_event(
                sequence=len(events) + 1,
                previous_digest=events[-1].event_digest if events else _ZERO_DIGEST,
                action="reconciliation_approval_consumption_started",
                actor=approved.actor,
                approval_id=approved.approval_id,
                operation_id=approved.operation_id,
                provider=approved.provider,
                project=approved.project,
                environment=approved.environment,
                journal_phase=approved.journal_phase,
                target_deployment_id=approved.target_deployment_id,
                previous_deployment_id=approved.previous_deployment_id,
                candidate_runtime_id=approved.candidate_runtime_id,
                previous_runtime_id=approved.previous_runtime_id,
                proposal_digest=approved.proposal_digest,
                evidence_digest=approved.evidence_digest,
                recorded_at=recorded_at or self._now(),
            )
            self._append_unlocked(event, events)
            return event

    def finish_approval_consumption(
        self,
        *,
        approval_id: str,
        proposal_digest: str,
        evidence_digest: str,
        action: AuditAction,
        recorded_at: str | None = None,
    ) -> ReconciliationAuditEnvelope:
        """Record the terminal result of a previously claimed grant."""
        if action not in {"reconciliation_approval_consumed", "reconciliation_rejected"}:
            raise ValueError("invalid approval consumption result action")
        with exclusive_process_lock(self.lock_path), self._lock:
            if os.name == "posix" and self.lock_path.exists():
                os.chmod(self.lock_path, 0o600)
            events = self._read_unlocked()
            approved = [
                item for item in events
                if item.action == "reconciliation_approved"
                and item.approval_id == approval_id
            ]
            started = [
                item for item in events
                if item.action == "reconciliation_approval_consumption_started"
                and item.approval_id == approval_id
            ]
            terminal = [
                item for item in events
                if item.approval_id == approval_id
                and item.action in {
                    "reconciliation_approval_consumed",
                    "reconciliation_rejected",
                }
                and any(
                    prior.sequence < item.sequence for prior in started
                )
            ]
            if (
                len(approved) != 1
                or len(started) != 1
                or terminal
                or approved[0].proposal_digest != proposal_digest
                or approved[0].evidence_digest != evidence_digest
                or not self._approval_scope_matches(approved[0], started[0])
                or approved[0].actor != started[0].actor
            ):
                raise ReconciliationAuditIntegrityError(
                    "approval consumption claim is missing, mismatched, or already finalized"
                )
            source = started[0]
            event = self._build_event(
                sequence=len(events) + 1,
                previous_digest=events[-1].event_digest if events else _ZERO_DIGEST,
                action=action,
                actor=source.actor,
                approval_id=source.approval_id,
                operation_id=source.operation_id,
                provider=source.provider,
                project=source.project,
                environment=source.environment,
                journal_phase=source.journal_phase,
                target_deployment_id=source.target_deployment_id,
                previous_deployment_id=source.previous_deployment_id,
                candidate_runtime_id=source.candidate_runtime_id,
                previous_runtime_id=source.previous_runtime_id,
                proposal_digest=source.proposal_digest,
                evidence_digest=source.evidence_digest,
                recorded_at=recorded_at or self._now(),
            )
            self._append_unlocked(event, events)
            return event

    def events(
        self, *, operation_id: str | None = None
    ) -> tuple[ReconciliationAuditEnvelope, ...]:
        """Return verified events; a malformed record fails the entire read."""
        if operation_id is not None and (
            not isinstance(operation_id, str) or not operation_id.strip()
        ):
            raise ValueError("operation_id must be a non-empty string when provided")
        with exclusive_process_lock(self.lock_path), self._lock:
            events = self._read_unlocked()
        if operation_id is None:
            return events
        return tuple(item for item in events if item.operation_id == operation_id)

    def verify(
        self,
        *,
        trusted_head: ReconciliationAuditHead | None = None,
    ) -> ReconciliationAuditHead:
        """Verify the chain and optionally compare it with an external checkpoint."""
        if trusted_head is not None and not isinstance(
            trusted_head, ReconciliationAuditHead
        ):
            raise TypeError("trusted_head must be a ReconciliationAuditHead")
        with exclusive_process_lock(self.lock_path), self._lock:
            events = self._read_unlocked()
        head = (
            ReconciliationAuditHead(0, _ZERO_DIGEST)
            if not events
            else ReconciliationAuditHead(
                events[-1].sequence, events[-1].event_digest
            )
        )
        if trusted_head is not None and head != trusted_head:
            raise ReconciliationAuditIntegrityError(
                "audit ledger head does not match the externally trusted checkpoint"
            )
        return head
