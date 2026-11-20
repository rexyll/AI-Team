"""Host-side synchronous completion witnesses for Local Docker reconciliation.

This is deliberately distinct from provider-native operation inspection:
the receipt proves that one synchronous Host adapter call returned, while
runtime and route postconditions must still be inspected independently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Mapping

from runtime.deployment_provider_operation_ledger import (
    DurableProviderOperationReceiptStore,
    provider_operation_request_digest,
)
from runtime.deployment_replacement import ReplacementJournalRecord

ReconciliationDecision = Literal["abort_candidate", "confirm_previous_retired"]
ReceiptAction = Literal["abort_candidate", "retire_previous"]
_COMPLETION_ACTION: Mapping[str, ReceiptAction] = {
    "abort_candidate": "abort_candidate",
    "confirm_previous_retired": "retire_previous",
}
_SOURCE_ID = "docker-local-host-call-receipts"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HostSynchronousOperationCompletionError(RuntimeError):
    """A Host call receipt cannot prove the requested synchronous completion."""


def _timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HostSynchronousOperationCompletionError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HostSynchronousOperationCompletionError(
            f"{field} is not a valid ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HostSynchronousOperationCompletionError(
            f"{field} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class HostSynchronousOperationCompletion:
    """Typed witness that one exact synchronous Host adapter call returned."""

    provider: str
    project: str
    environment: str
    operation_id: str
    decision: ReconciliationDecision
    action: ReceiptAction
    source_id: str
    started_at: str
    completed_at: str
    request_digest_sha256: str
    response_digest_sha256: str
    completion_type: Literal["host_synchronous_call_return"] = (
        "host_synchronous_call_return"
    )
    result_status: Literal["succeeded"] = "succeeded"

    def __post_init__(self) -> None:
        for name in ("provider", "project", "environment", "operation_id", "source_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.provider != "docker-local":
            raise ValueError("Host synchronous completion is restricted to docker-local")
        if self.decision not in _COMPLETION_ACTION:
            raise ValueError("unsupported reconciliation decision")
        if self.action != _COMPLETION_ACTION[self.decision]:
            raise ValueError("receipt action does not match the reconciliation decision")
        if self.source_id != _SOURCE_ID:
            raise ValueError("unexpected Host call receipt source")
        if self.completion_type != "host_synchronous_call_return":
            raise ValueError("unsupported completion proof type")
        if self.result_status != "succeeded":
            raise ValueError("only a successful synchronous call can prove completion")
        started = _timestamp(self.started_at, "started_at")
        completed = _timestamp(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("completed_at must not precede started_at")
        for name in ("request_digest_sha256", "response_digest_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")


class LocalDockerSynchronousOperationCompletionInspector:
    """Read-only inspector over the Host's existing provider-call sidecar.

    The inspector never creates the sidecar. It accepts only returned,
    successful receipts whose exact request digest can be recomputed from the
    immutable journal identities. It does not inspect Docker or claim a
    provider-issued operation resource exists.
    """

    name = "docker-local-host-call-receipts"
    source_id = _SOURCE_ID

    def __init__(
        self,
        receipt_store_path: str | Path,
        *,
        max_evidence_age_seconds: float = 120.0,
        clock=None,
    ) -> None:
        if not isinstance(receipt_store_path, (str, Path)) or not str(
            receipt_store_path
        ).strip():
            raise ValueError("receipt_store_path must be a non-empty path")
        if (
            isinstance(max_evidence_age_seconds, bool)
            or not isinstance(max_evidence_age_seconds, (int, float))
            or max_evidence_age_seconds <= 0
        ):
            raise ValueError("max_evidence_age_seconds must be positive")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self.receipt_store_path = Path(receipt_store_path).expanduser().resolve()
        self.max_age = timedelta(seconds=float(max_evidence_age_seconds))
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise HostSynchronousOperationCompletionError(
                "Host completion inspector clock must be timezone-aware"
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _expected_binding(
        record: ReplacementJournalRecord, decision: ReconciliationDecision
    ) -> dict[str, str]:
        candidate_id = record.candidate_runtime_id
        previous_id = record.previous_runtime_id
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise HostSynchronousOperationCompletionError(
                "journal candidate immutable runtime ID is missing"
            )
        if not isinstance(previous_id, str) or not previous_id.strip():
            raise HostSynchronousOperationCompletionError(
                "journal previous immutable runtime ID is missing"
            )
        if decision == "abort_candidate":
            return {
                "candidate_deployment_id": record.target_deployment_id,
                "candidate_runtime_id": candidate_id,
                "previous_runtime_id": previous_id,
            }
        return {
            "previous_deployment_id": record.previous_deployment_id,
            "previous_runtime_id": previous_id,
        }

    def inspect_completion(
        self,
        record: ReplacementJournalRecord,
        decision: ReconciliationDecision,
    ) -> HostSynchronousOperationCompletion:
        """Read and validate the exact action receipt for one journal decision."""
        if not isinstance(record, ReplacementJournalRecord):
            raise TypeError("record must be a ReplacementJournalRecord")
        if decision not in _COMPLETION_ACTION:
            raise HostSynchronousOperationCompletionError(
                "unsupported reconciliation decision"
            )
        if record.phase != "needs_reconciliation":
            raise HostSynchronousOperationCompletionError(
                "journal must be in needs_reconciliation phase"
            )
        if record.provider != "docker-local":
            raise HostSynchronousOperationCompletionError(
                "Host synchronous completion is restricted to docker-local"
            )
        action = _COMPLETION_ACTION[decision]
        binding = self._expected_binding(record, decision)
        expected_digest = provider_operation_request_digest(
            provider=record.provider,
            project=record.project,
            environment=record.environment,
            operation_id=record.operation_id,
            operation_name=action,
            binding=binding,
        )

        try:
            store = DurableProviderOperationReceiptStore(
                self.receipt_store_path, read_only=True
            )
            receipt = store.get_operation_receipt(
                provider=record.provider,
                project=record.project,
                environment=record.environment,
                operation_id=record.operation_id,
                operation_name=action,
            )
        except FileNotFoundError as exc:
            raise HostSynchronousOperationCompletionError(
                "Host provider-call receipt sidecar is missing"
            ) from exc
        except Exception as exc:
            raise HostSynchronousOperationCompletionError(
                "Host provider-call receipt sidecar could not be read"
            ) from exc

        if receipt is None:
            raise HostSynchronousOperationCompletionError(
                "exact Host provider-call receipt is missing"
            )
        if (
            receipt.provider != record.provider
            or receipt.project != record.project
            or receipt.environment != record.environment
            or receipt.operation_id != record.operation_id
            or receipt.operation_name != action
        ):
            raise HostSynchronousOperationCompletionError(
                "Host provider-call receipt scope/action does not match the journal"
            )
        if receipt.state != "returned":
            raise HostSynchronousOperationCompletionError(
                f"Host provider-call receipt is not terminal: {receipt.state}"
            )
        if receipt.provider_result_status != "succeeded":
            raise HostSynchronousOperationCompletionError(
                "Host synchronous provider call did not report success"
            )
        if receipt.request_digest_sha256 != expected_digest:
            raise HostSynchronousOperationCompletionError(
                "Host provider-call request digest does not match immutable journal scope"
            )
        if not isinstance(receipt.response_digest_sha256, str) or not _SHA256.fullmatch(
            receipt.response_digest_sha256
        ):
            raise HostSynchronousOperationCompletionError(
                "Host provider-call response digest is missing or invalid"
            )

        started = _timestamp(receipt.started_at, "receipt started_at")
        completed = _timestamp(receipt.completed_at, "receipt completed_at")
        now = self._now()
        if completed < started:
            raise HostSynchronousOperationCompletionError(
                "receipt completion timestamp precedes its start"
            )
        if completed > now:
            raise HostSynchronousOperationCompletionError(
                "receipt completion timestamp is future-dated"
            )
        if now - completed > self.max_age:
            raise HostSynchronousOperationCompletionError(
                "Host provider-call receipt is stale"
            )

        return HostSynchronousOperationCompletion(
            provider=record.provider,
            project=record.project,
            environment=record.environment,
            operation_id=record.operation_id,
            decision=decision,
            action=action,
            source_id=self.source_id,
            started_at=receipt.started_at,
            completed_at=receipt.completed_at,
            request_digest_sha256=receipt.request_digest_sha256,
            response_digest_sha256=receipt.response_digest_sha256,
        )
