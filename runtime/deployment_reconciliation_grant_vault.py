"""Protected custody for one-use reconciliation approval grants.

The vault persists only an authenticated ciphertext envelope. The injected
protector must use an external KMS/SecretStore-managed key and bind the supplied
encryption context as authenticated additional data. No software-key fallback
or plaintext-on-disk mode is provided.

This module does not authenticate operators, issue approvals, consume approvals,
or execute reconciliation actions.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import stat
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol

from runtime.deployment_reconciliation_authority import (
    ReconciliationApprovalGrant,
    ReconciliationApprovalGrantReference,
)
from runtime.deployment_reconciliation_contract import (
    AuthenticatedPrincipal,
    ReconciliationApproval,
    ReconciliationEvidence,
    ReconciliationProposal,
    ReconciliationSnapshotReadReceipt,
    reconciliation_evidence_digest,
)
from runtime.deployment_replacement import ReplacementJournalRecord

_APPROVAL_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = 1
_MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
_CONTEXT_KEYS = frozenset(
    {
        "purpose",
        "schema_version",
        "approval_id",
        "operation_id",
        "provider",
        "project",
        "environment",
        "expires_at",
        "proposal_digest",
        "evidence_digest",
    }
)


class ReconciliationGrantVaultError(RuntimeError):
    """A protected grant cannot be safely stored, restored, or removed."""


class ReconciliationGrantProtector(Protocol):
    """External key-management boundary for grant encryption.

    Implementations must use a key managed outside the writable grant-vault
    directory, provide authenticated encryption, and bind every context item
    as authenticated additional data. For KMS services with small direct-
    encryption limits, implementations must use an envelope-encryption flow.
    """

    def seal(
        self,
        plaintext: bytes,
        *,
        encryption_context: Mapping[str, str],
    ) -> bytes:
        """Return an opaque authenticated ciphertext envelope."""
        ...

    def unseal(
        self,
        ciphertext: bytes,
        *,
        encryption_context: Mapping[str, str],
    ) -> bytes:
        """Authenticate the context and decrypt the exact ciphertext envelope."""
        ...


class ReconciliationApprovalGrantVault:
    """Persist and restore encrypted grant material through an injected KMS.

    The local directory contains only ciphertext plus non-secret scope metadata.
    POSIX directories/files are required to be private and owned by the service
    account. Windows ACL enforcement remains the responsibility of the Host
    deployment service and the injected SecretStore/KMS adapter.
    """

    DIRECTORY_MODE = 0o700
    FILE_MODE = 0o600
    FILE_SUFFIX = ".grant"

    def __init__(
        self,
        root: str | Path,
        *,
        protector: ReconciliationGrantProtector,
        clock=None,
    ) -> None:
        if not isinstance(root, (str, Path)) or not str(root).strip():
            raise ValueError("root must be a non-empty path")
        if protector is None or not callable(getattr(protector, "seal", None)) or not callable(
            getattr(protector, "unseal", None)
        ):
            raise TypeError("an external ReconciliationGrantProtector is required")
        self._protector = protector
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        supplied = Path(root).expanduser()
        supplied.mkdir(parents=True, exist_ok=True, mode=self.DIRECTORY_MODE)
        if supplied.is_symlink() or not supplied.is_dir():
            raise ReconciliationGrantVaultError(
                "grant vault root must be a real directory"
            )
        self.root = supplied.resolve()
        self._validate_root()

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ReconciliationGrantVaultError(
                "grant vault clock must return a timezone-aware datetime"
            )
        return value.astimezone(timezone.utc)

    def _validate_root(self) -> None:
        if self.root.is_symlink() or not self.root.is_dir():
            raise ReconciliationGrantVaultError(
                "grant vault root is unavailable or untrusted"
            )
        if os.name == "posix":
            try:
                metadata = self.root.stat(follow_symlinks=False)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                ):
                    raise ReconciliationGrantVaultError(
                        "grant vault root ownership or permissions are unsafe"
                    )
            except OSError as exc:
                raise ReconciliationGrantVaultError(
                    "grant vault root could not be inspected"
                ) from exc

    @staticmethod
    def _canonical(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _approval_id(grant: ReconciliationApprovalGrant) -> str:
        if not isinstance(grant, ReconciliationApprovalGrant):
            raise TypeError("grant must be a ReconciliationApprovalGrant")
        proposal = grant.proposal
        if not isinstance(proposal, ReconciliationProposal):
            raise ReconciliationGrantVaultError("grant proposal is invalid")
        approval_id = proposal.approval.approval_id
        if not isinstance(approval_id, str) or not _APPROVAL_ID.fullmatch(
            approval_id
        ):
            raise ReconciliationGrantVaultError(
                "grant approval identifier is not safe for persistent storage"
            )
        return approval_id

    @staticmethod
    def _calculate_proposal_digest(
        proposal: ReconciliationProposal,
        evidence_digest: str,
    ) -> str:
        receipt = proposal.snapshot_receipt
        if not isinstance(receipt, ReconciliationSnapshotReadReceipt):
            raise ReconciliationGrantVaultError(
                "grant proposal has no trusted snapshot receipt"
            )
        payload = {
            "operation": proposal.approval.operation,
            "record": asdict(proposal.record),
            "evidence_digest": evidence_digest,
            "snapshot_provenance_digest": receipt.approval_binding_digest(),
        }
        return hashlib.sha256(
            ReconciliationApprovalGrantVault._canonical(payload)
        ).hexdigest()

    def _validate_grant(self, grant: ReconciliationApprovalGrant) -> dict[str, str]:
        approval_id = self._approval_id(grant)
        proposal = grant.proposal
        approval = proposal.approval
        if not isinstance(grant.token, str) or len(grant.token) < 32:
            raise ReconciliationGrantVaultError("grant bearer token is invalid")
        actual_evidence_digest = reconciliation_evidence_digest(proposal.evidence)
        actual_proposal_digest = self._calculate_proposal_digest(
            proposal, actual_evidence_digest
        )
        if (
            not isinstance(grant.evidence_digest, str)
            or not _SHA256.fullmatch(grant.evidence_digest)
            or not secrets.compare_digest(
                actual_evidence_digest, grant.evidence_digest
            )
        ):
            raise ReconciliationGrantVaultError(
                "grant evidence digest does not match its proposal"
            )
        if (
            not isinstance(grant.proposal_digest, str)
            or not _SHA256.fullmatch(grant.proposal_digest)
            or not secrets.compare_digest(
                actual_proposal_digest, grant.proposal_digest
            )
        ):
            raise ReconciliationGrantVaultError(
                "grant proposal digest does not match its proposal"
            )
        try:
            expiry = datetime.fromisoformat(
                approval.expires_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (AttributeError, ValueError) as exc:
            raise ReconciliationGrantVaultError(
                "grant expiry timestamp is invalid"
            ) from exc
        if self._now() >= expiry:
            raise ReconciliationGrantVaultError("expired approval grants cannot be stored or restored")
        return {
            "purpose": "ai-team-reconciliation-approval-grant",
            "schema_version": str(_SCHEMA_VERSION),
            "approval_id": approval_id,
            "operation_id": proposal.record.operation_id,
            "provider": proposal.record.provider,
            "project": proposal.record.project,
            "environment": proposal.record.environment,
            "expires_at": approval.expires_at,
            "proposal_digest": grant.proposal_digest,
            "evidence_digest": grant.evidence_digest,
        }

    @staticmethod
    def _encode_grant(grant: ReconciliationApprovalGrant) -> bytes:
        proposal = grant.proposal
        receipt = proposal.snapshot_receipt
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "proposal": {
                "record": asdict(proposal.record),
                "approval": asdict(proposal.approval),
                "evidence": [asdict(item) for item in proposal.evidence],
                "proposed_at": proposal.proposed_at,
                "snapshot_receipt": asdict(receipt) if receipt is not None else None,
            },
            "proposal_digest": grant.proposal_digest,
            "evidence_digest": grant.evidence_digest,
            "token": grant.token,
        }
        return ReconciliationApprovalGrantVault._canonical(payload)

    @staticmethod
    def _decode_grant(plaintext: bytes) -> ReconciliationApprovalGrant:
        try:
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "proposal",
                "proposal_digest",
                "evidence_digest",
                "token",
            }:
                raise ValueError("grant payload fields are invalid")
            if payload["schema_version"] != _SCHEMA_VERSION:
                raise ValueError("grant payload schema is unsupported")
            proposal_data = payload["proposal"]
            if not isinstance(proposal_data, dict) or set(proposal_data) != {
                "record",
                "approval",
                "evidence",
                "proposed_at",
                "snapshot_receipt",
            }:
                raise ValueError("grant proposal fields are invalid")
            record = ReplacementJournalRecord(**proposal_data["record"])
            approval_data = dict(proposal_data["approval"])
            approval_data["requested_by"] = AuthenticatedPrincipal(
                **approval_data["requested_by"]
            )
            approval_data["approved_by"] = AuthenticatedPrincipal(
                **approval_data["approved_by"]
            )
            approval = ReconciliationApproval(**approval_data)
            evidence_data = proposal_data["evidence"]
            if not isinstance(evidence_data, list):
                raise ValueError("grant evidence must be an array")
            evidence = tuple(
                ReconciliationEvidence(**item) for item in evidence_data
            )
            receipt_data = proposal_data["snapshot_receipt"]
            receipt = None
            if receipt_data is not None:
                receipt_data = dict(receipt_data)
                receipt_data["evidence_sources"] = tuple(
                    receipt_data["evidence_sources"]
                )
                receipt = ReconciliationSnapshotReadReceipt(**receipt_data)
            proposal = ReconciliationProposal(
                record=record,
                approval=approval,
                evidence=evidence,
                proposed_at=proposal_data["proposed_at"],
                snapshot_receipt=receipt,
            )
            grant = ReconciliationApprovalGrant(
                proposal=proposal,
                proposal_digest=payload["proposal_digest"],
                evidence_digest=payload["evidence_digest"],
                token=payload["token"],
            )
        except Exception as exc:
            raise ReconciliationGrantVaultError(
                "decrypted approval grant payload is malformed"
            ) from exc
        return grant

    def _path(self, approval_id: str) -> Path:
        if not isinstance(approval_id, str) or not _APPROVAL_ID.fullmatch(
            approval_id
        ):
            raise ValueError("approval_id is malformed")
        return self.root / f"{approval_id}{self.FILE_SUFFIX}"

    def save(
        self, grant: ReconciliationApprovalGrant
    ) -> ReconciliationApprovalGrantReference:
        """Encrypt and persist a new grant; existing approval IDs are never replaced."""
        context = self._validate_grant(grant)
        plaintext = self._encode_grant(grant)
        try:
            ciphertext = self._protector.seal(
                plaintext, encryption_context=context
            )
        except Exception as exc:
            raise ReconciliationGrantVaultError(
                "external grant protector could not seal the approval grant"
            ) from exc
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ReconciliationGrantVaultError(
                "external grant protector returned an invalid ciphertext envelope"
            )
        outer = {
            "schema_version": _SCHEMA_VERSION,
            "context": context,
            "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        }
        raw = self._canonical(outer)
        if len(raw) > _MAX_ENVELOPE_BYTES:
            raise ReconciliationGrantVaultError(
                "protected approval grant envelope exceeds the size limit"
            )
        path = self._path(context["approval_id"])
        self._validate_root()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = None
        try:
            fd = os.open(path, flags, self.FILE_MODE)
            if os.name == "posix":
                os.fchmod(fd, self.FILE_MODE)
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write while saving grant envelope")
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = None
            if os.name == "posix":
                directory_fd = os.open(
                    self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except FileExistsError as exc:
            raise ReconciliationGrantVaultError(
                "an approval grant with this ID is already stored"
            ) from exc
        except Exception as exc:
            if fd is not None:
                os.close(fd)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ReconciliationGrantVaultError(
                "protected approval grant could not be durably written"
            ) from exc
        return ReconciliationApprovalGrantReference(
            approval_id=context["approval_id"],
            envelope_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def _read_raw(self, approval_id: str) -> bytes:
        """Read one private envelope without following symlinks."""
        self._validate_root()
        path = self._path(approval_id)
        if path.is_symlink():
            raise ReconciliationGrantVaultError(
                "grant envelope must not be a symlink"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ReconciliationGrantVaultError(
                        "grant envelope is not a regular file"
                    )
                if os.name == "posix" and (
                    metadata.st_uid != os.getuid()
                    or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                ):
                    raise ReconciliationGrantVaultError(
                        "grant envelope ownership or permissions are unsafe"
                    )
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_ENVELOPE_BYTES:
                        raise ReconciliationGrantVaultError(
                            "grant envelope exceeds the size limit"
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                os.close(fd)
        except ReconciliationGrantVaultError:
            raise
        except OSError as exc:
            raise ReconciliationGrantVaultError(
                "grant envelope is unavailable or could not be safely opened"
            ) from exc

    def reference_for(self, approval_id: str) -> ReconciliationApprovalGrantReference:
        """Rebuild a non-secret reference when a caller lost the return value.

        The approval ID can be recovered from the approved audit event. The
        caller must still load the grant and let the audit store validate the
        token digest before attempting consumption.
        """
        raw = self._read_raw(approval_id)
        reference = ReconciliationApprovalGrantReference(
            approval_id=approval_id,
            envelope_sha256=hashlib.sha256(raw).hexdigest(),
        )
        self._read_envelope(reference)
        return reference

    def _read_envelope(
        self, reference: ReconciliationApprovalGrantReference
    ) -> tuple[bytes, dict[str, str], bytes]:
        if not isinstance(reference, ReconciliationApprovalGrantReference):
            raise TypeError("reference must be a ReconciliationApprovalGrantReference")
        raw = self._read_raw(reference.approval_id)
        if not secrets.compare_digest(
            hashlib.sha256(raw).hexdigest(), reference.envelope_sha256
        ):
            raise ReconciliationGrantVaultError(
                "grant envelope does not match its durable reference"
            )
        try:
            outer = json.loads(raw.decode("utf-8"))
            if not isinstance(outer, dict) or set(outer) != {
                "schema_version",
                "context",
                "ciphertext_b64",
            }:
                raise ValueError("envelope fields are invalid")
            if outer["schema_version"] != _SCHEMA_VERSION:
                raise ValueError("envelope schema is unsupported")
            context = outer["context"]
            if (
                not isinstance(context, dict)
                or set(context) != _CONTEXT_KEYS
                or any(not isinstance(value, str) or not value for value in context.values())
                or context["approval_id"] != reference.approval_id
                or context["purpose"] != "ai-team-reconciliation-approval-grant"
                or context["schema_version"] != str(_SCHEMA_VERSION)
            ):
                raise ValueError("envelope encryption context is invalid")
            ciphertext = base64.b64decode(
                outer["ciphertext_b64"], validate=True
            )
            if not ciphertext:
                raise ValueError("ciphertext is empty")
        except Exception as exc:
            raise ReconciliationGrantVaultError(
                "protected approval grant envelope is malformed"
            ) from exc
        return raw, context, ciphertext
    def load(
        self, reference: ReconciliationApprovalGrantReference
    ) -> ReconciliationApprovalGrant:
        """Restore an unexpired grant only after ciphertext and context validation."""
        _, context, ciphertext = self._read_envelope(reference)
        try:
            plaintext = self._protector.unseal(
                ciphertext, encryption_context=context
            )
        except Exception as exc:
            raise ReconciliationGrantVaultError(
                "external grant protector rejected the ciphertext or context"
            ) from exc
        if not isinstance(plaintext, bytes) or not plaintext:
            raise ReconciliationGrantVaultError(
                "external grant protector returned invalid plaintext"
            )
        if len(plaintext) > _MAX_ENVELOPE_BYTES:
            raise ReconciliationGrantVaultError(
                "decrypted approval grant exceeds the size limit"
            )
        grant = self._decode_grant(plaintext)
        expected_context = self._validate_grant(grant)
        if expected_context != context:
            raise ReconciliationGrantVaultError(
                "decrypted approval grant does not match its protected scope"
            )
        return replace(grant, storage_reference=reference)

    def delete(
        self, reference: ReconciliationApprovalGrantReference
    ) -> None:
        """Remove a ciphertext envelope after caller-confirmed terminal handling."""
        self._read_envelope(reference)
        path = self._path(reference.approval_id)
        try:
            path.unlink()
            if os.name == "posix":
                directory_fd = os.open(
                    self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as exc:
            raise ReconciliationGrantVaultError(
                "protected approval grant could not be removed"
            ) from exc
