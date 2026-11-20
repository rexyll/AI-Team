"""Read-only, journal-revision-fenced reconciliation snapshot reader.

The Host supplies a trusted evidence collector for its real provider, immutable
runtime and traffic-route APIs. This adapter binds those observations to one
SQLite journal revision by reading the journal before and after collection.
It never mutates deployment history or provider resources.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import uuid4

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_reconciliation_authority import (
    ReconciliationCurrentSnapshot,
)
from runtime.deployment_reconciliation_contract import (
    ReconciliationEvidence,
    ReconciliationOperation,
    ReconciliationSnapshotReadReceipt,
    reconciliation_evidence_digest,
    reconciliation_record_digest,
)
from runtime.deployment_replacement import ReplacementJournalRecord


class ReconciliationSnapshotReadError(RuntimeError):
    """A current journal/evidence snapshot could not be established safely."""


class ReconciliationJournalChangedError(ReconciliationSnapshotReadError):
    """The durable replacement journal changed during evidence collection."""


class ReconciliationEvidenceCollector(Protocol):
    """Trusted Host boundary for source-authenticated, operation-specific evidence.

    Implementations must inspect provider operation state, exact immutable
    runtime identities, health and the effective traffic route. They must
    return digest-addressed evidence from authenticated live sources; timeouts,
    unknown states, identity mismatches or invalid responses are not positive
    evidence and must fail closed.
    """

    def collect_current_evidence(
        self,
        record: ReplacementJournalRecord,
        operation: ReconciliationOperation,
        *,
        snapshot_started_at: str | None = None,
    ) -> tuple[ReconciliationEvidence, ...]:
        """Collect the exact evidence kinds required by the resolution policy."""
        ...


class DeploymentHistoryReconciliationSnapshotReader:
    """Bind trusted live evidence to an unchanged Host SQLite journal revision.

    This adapter performs two independent journal reads around the evidence
    collection. The canonical journal-record digest acts as the revision token.
    It is an optimistic fence, not a distributed transaction across Docker,
    cloud-provider and router APIs. Evidence source authentication and
    correctness remain responsibilities of the injected collector.
    """

    def __init__(
        self,
        history: DeploymentHistoryStore,
        evidence_collector: ReconciliationEvidenceCollector,
        *,
        reader_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(history, "get_replacement", None)):
            raise TypeError("history must expose a read-only get_replacement method")
        if not callable(
            getattr(evidence_collector, "collect_current_evidence", None)
        ):
            raise TypeError("a trusted ReconciliationEvidenceCollector is required")
        if not isinstance(reader_id, str) or not reader_id.strip():
            raise ValueError("reader_id must be a non-empty string")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._history = history
        self._evidence_collector = evidence_collector
        self.reader_id = reader_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ReconciliationSnapshotReadError(
                "Host clock must return a timezone-aware datetime"
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def read_current_snapshot(
        self,
        operation_id: str,
        operation: ReconciliationOperation,
    ) -> ReconciliationCurrentSnapshot:
        """Read, collect and revision-fence one current reconciliation snapshot."""
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("operation_id must be a non-empty string")
        if operation not in {"abort_candidate", "confirm_previous_retired"}:
            raise ValueError("unsupported reconciliation operation")

        read_started = self._now()
        try:
            before = self._history.get_replacement(operation_id)
        except Exception as exc:
            raise ReconciliationSnapshotReadError(
                "durable replacement journal read failed before evidence collection"
            ) from exc
        if not isinstance(before, ReplacementJournalRecord):
            raise ReconciliationSnapshotReadError(
                "durable replacement journal was not found or returned an invalid record"
            )
        if before.operation_id != operation_id:
            raise ReconciliationSnapshotReadError(
                "durable replacement journal operation ID does not match the request"
            )
        if before.phase != "needs_reconciliation":
            raise ReconciliationSnapshotReadError(
                "only needs_reconciliation journal records can be snapshotted"
            )
        if not before.candidate_runtime_id or not before.previous_runtime_id:
            raise ReconciliationSnapshotReadError(
                "journal is missing immutable candidate or previous runtime identity"
            )

        try:
            evidence = self._evidence_collector.collect_current_evidence(
                before, operation, snapshot_started_at=self._iso(read_started)
            )
        except Exception as exc:
            raise ReconciliationSnapshotReadError(
                "trusted provider/runtime/route evidence collection failed"
            ) from exc
        if not isinstance(evidence, tuple) or any(
            not isinstance(item, ReconciliationEvidence) for item in evidence
        ):
            raise ReconciliationSnapshotReadError(
                "evidence collector returned an invalid evidence tuple"
            )

        try:
            after = self._history.get_replacement(operation_id)
        except Exception as exc:
            raise ReconciliationSnapshotReadError(
                "durable replacement journal reread failed after evidence collection"
            ) from exc
        read_completed = self._now()
        if not isinstance(after, ReplacementJournalRecord):
            raise ReconciliationSnapshotReadError(
                "durable replacement journal disappeared during evidence collection"
            )
        before_revision = reconciliation_record_digest(before)
        after_revision = reconciliation_record_digest(after)
        if before != after or before_revision != after_revision:
            raise ReconciliationJournalChangedError(
                "durable replacement journal revision changed during evidence collection"
            )

        receipt = ReconciliationSnapshotReadReceipt(
            reader_id=self.reader_id,
            snapshot_id=uuid4().hex,
            operation_id=operation_id,
            journal_revision_before=before_revision,
            journal_revision_after=after_revision,
            record_digest=reconciliation_record_digest(after),
            evidence_digest=reconciliation_evidence_digest(evidence),
            evidence_sources=tuple(sorted({item.source for item in evidence})),
            read_started_at=self._iso(read_started),
            read_completed_at=self._iso(read_completed),
        )
        try:
            receipt.verify_snapshot(after, evidence)
        except (TypeError, ValueError) as exc:
            raise ReconciliationSnapshotReadError(
                "snapshot receipt failed to bind the collected journal/evidence"
            ) from exc
        return ReconciliationCurrentSnapshot(after, evidence, receipt)
