"""Fail-closed external checkpointing for the reconciliation audit hash chain.

This adapter contract deliberately selects no cloud vendor. A production anchor
must provide a durable, linearizable compare-and-set operation stored outside
the writable audit directory. A local append is accepted only when its new head
has been confirmed at the external anchor.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable, Protocol, TypeVar

from runtime.deployment_reconciliation_audit_store import (
    DurableReconciliationAuditStore,
    ReconciliationAuditHead,
)
from runtime.process_lock import exclusive_process_lock


class ReconciliationAuditHeadAnchor(Protocol):
    """External trust root for one audit ledger head.

    Implementations must store the checkpoint outside the audit directory,
    durably persist updates, and implement compare_and_set atomically across
    every Host that can write this ledger. Missing/uninitialized checkpoints
    must fail closed; production provisioning must explicitly initialize the
    genesis head before any audit event is accepted.
    """

    def read_head(self) -> ReconciliationAuditHead:
        """Read the current durable checkpoint."""
        ...

    def compare_and_set(
        self,
        expected: ReconciliationAuditHead,
        replacement: ReconciliationAuditHead,
    ) -> bool:
        """Atomically replace exactly expected with replacement and fsync/commit."""
        ...


class ReconciliationAuditAnchorError(RuntimeError):
    """The local audit ledger cannot be verified against its external anchor."""


class ReconciliationAuditAnchorConflict(ReconciliationAuditAnchorError):
    """The external checkpoint did not advance to the exact new local head."""


_Result = TypeVar("_Result")


class ExternallyAnchoredReconciliationAuditStore(DurableReconciliationAuditStore):
    """Durable local ledger that requires a remote checkpoint for every append.

    Writes are serialized with a second same-host lock, then the local chain is
    checked against the external head, one event is appended/fsynced, and the
    external head is advanced with a linearizable compare-and-set. The class
    refuses to auto-reconcile a local-ahead/anchor-behind state: a crash between
    local append and remote CAS therefore blocks subsequent reads and writes
    until an operator investigates and repairs the external checkpoint.

    This same-host lock is not a substitute for a shared database or distributed
    transaction when multiple hosts use independent local audit files.
    """

    ANCHOR_LOCK_NAME = ".deployment-reconciliation-audit-anchor.lock"

    def __init__(
        self,
        root: str | Path,
        *,
        anchor: ReconciliationAuditHeadAnchor,
    ) -> None:
        if anchor is None or not callable(
            getattr(anchor, "read_head", None)
        ) or not callable(getattr(anchor, "compare_and_set", None)):
            raise TypeError("a trusted external ReconciliationAuditHeadAnchor is required")
        super().__init__(root)
        self._anchor = anchor
        self.anchor_lock_path = self.root / self.ANCHOR_LOCK_NAME
        if self.anchor_lock_path.is_symlink():
            raise ReconciliationAuditAnchorError(
                "external-anchor coordination lock must not be a symlink"
            )

    def _anchor_lock(self):
        return exclusive_process_lock(self.anchor_lock_path)

    def _read_external_head(self) -> ReconciliationAuditHead:
        try:
            head = self._anchor.read_head()
        except Exception as exc:
            raise ReconciliationAuditAnchorError(
                "external audit-head anchor is unavailable"
            ) from exc
        if not isinstance(head, ReconciliationAuditHead):
            raise ReconciliationAuditAnchorError(
                "external audit-head anchor returned an invalid checkpoint"
            )
        return head

    def _validate_anchor_lock_file(self) -> None:
        try:
            metadata = self.anchor_lock_path.stat(follow_symlinks=False)
        except OSError as exc:
            raise ReconciliationAuditAnchorError(
                "external-anchor coordination lock could not be inspected"
            ) from exc
        if (
            self.anchor_lock_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or (
                os.name == "posix"
                and (
                    metadata.st_nlink != 1
                    or metadata.st_uid != os.getuid()
                )
            )
        ):
            raise ReconciliationAuditAnchorError(
                "external-anchor coordination lock is not a trusted regular file"
            )
        if os.name == "posix":
            os.chmod(self.anchor_lock_path, 0o600)

    def verify(
        self,
        *,
        trusted_head: ReconciliationAuditHead | None = None,
    ) -> ReconciliationAuditHead:
        """Verify the local chain against the external checkpoint, never a caller override."""
        with self._anchor_lock():
            self._validate_anchor_lock_file()
            external_head = self._read_external_head()
            if trusted_head is not None and trusted_head != external_head:
                raise ReconciliationAuditAnchorError(
                    "caller checkpoint differs from the configured external anchor"
                )
            try:
                return DurableReconciliationAuditStore.verify(
                    self, trusted_head=external_head
                )
            except Exception as exc:
                raise ReconciliationAuditAnchorError(
                    "local reconciliation audit head does not match the external checkpoint"
                ) from exc

    def events(
        self, *, operation_id: str | None = None
    ):
        """Return ledger events only while the complete local head is anchored."""
        with self._anchor_lock():
            self._validate_anchor_lock_file()
            external_head = self._read_external_head()
            try:
                DurableReconciliationAuditStore.verify(
                    self, trusted_head=external_head
                )
                return DurableReconciliationAuditStore.events(
                    self, operation_id=operation_id
                )
            except Exception as exc:
                raise ReconciliationAuditAnchorError(
                    "audit events are unavailable because the local head is not externally anchored"
                ) from exc

    def _anchored_write(self, operation: Callable[[], _Result]) -> _Result:
        with self._anchor_lock():
            self._validate_anchor_lock_file()
            expected = self._read_external_head()
            try:
                DurableReconciliationAuditStore.verify(
                    self, trusted_head=expected
                )
            except Exception as exc:
                raise ReconciliationAuditAnchorError(
                    "audit write refused because the local ledger differs from the external checkpoint"
                ) from exc

            result = operation()
            try:
                replacement = DurableReconciliationAuditStore.verify(self)
            except Exception as exc:
                raise ReconciliationAuditAnchorError(
                    "local audit append could not be verified after writing"
                ) from exc
            if replacement.sequence != expected.sequence + 1:
                raise ReconciliationAuditAnchorError(
                    "one anchored write must append exactly one audit event"
                )

            try:
                advanced = self._anchor.compare_and_set(expected, replacement)
            except Exception as exc:
                # A remote CAS may commit before a client loses its response.
                try:
                    if self._read_external_head() == replacement:
                        return result
                except Exception:
                    pass
                raise ReconciliationAuditAnchorError(
                    "external audit-head update outcome is ambiguous; ledger is fail-closed"
                ) from exc

            if not advanced:
                observed = self._read_external_head()
                if observed != replacement:
                    raise ReconciliationAuditAnchorConflict(
                        "external audit-head compare-and-set conflict; local append remains unanchored"
                    )
            confirmed = self._read_external_head()
            if confirmed != replacement:
                raise ReconciliationAuditAnchorError(
                    "external audit-head confirmation did not match the new local head"
                )
            return result

    def append(self, event):
        """Append one pre-built event and anchor the resulting chain head."""
        return self._anchored_write(
            lambda: DurableReconciliationAuditStore.append(self, event)
        )

    def record(self, *args, **kwargs):
        """Record one event and anchor the resulting chain head."""
        return self._anchored_write(
            lambda: DurableReconciliationAuditStore.record(self, *args, **kwargs)
        )

    def begin_approval_consumption(self, *args, **kwargs):
        """Atomically claim one approval and externally anchor the claim event."""
        return self._anchored_write(
            lambda: DurableReconciliationAuditStore.begin_approval_consumption(
                self, *args, **kwargs
            )
        )

    def finish_approval_consumption(self, *args, **kwargs):
        """Finish one approval claim and externally anchor the terminal event."""
        return self._anchored_write(
            lambda: DurableReconciliationAuditStore.finish_approval_consumption(
                self, *args, **kwargs
            )
        )
