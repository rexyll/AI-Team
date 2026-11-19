"""Durable Host receipts for synchronous deployment-provider calls.

The receipt ledger records when the Host entered and left a provider method.
It is not a provider-issued operation resource and cannot resolve a crash window:
an unfinished or ambiguous receipt remains unknown and must fail closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACTIONS = {
    "prepare_candidate",
    "start_candidate",
    "switch_traffic",
    "retire_previous",
    "abort_candidate",
}

ProviderOperationAction = Literal[
    "prepare_candidate",
    "start_candidate",
    "switch_traffic",
    "retire_previous",
    "abort_candidate",
]
ProviderOperationActionStatus = Literal["in_progress", "succeeded", "failed", "unknown"]
ProviderOperationInspectionStatus = Literal["not_found", "in_progress", "terminal", "unknown"]


def _non_empty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _aware_timestamp(value: str, field: str) -> None:
    _non_empty(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True)
class DeploymentProviderOperationActionReceipt:
    """One immutable Host record for a single provider method invocation."""

    provider: str
    project: str
    environment: str
    operation_id: str
    action: ProviderOperationAction
    status: ProviderOperationActionStatus
    request_digest: str
    result_digest: str | None
    started_at: str
    completed_at: str | None

    def __post_init__(self) -> None:
        for field in ("provider", "project", "environment", "operation_id"):
            _non_empty(getattr(self, field), field)
        if self.action not in _ACTIONS:
            raise ValueError("unsupported provider operation action")
        if self.status not in {"in_progress", "succeeded", "failed", "unknown"}:
            raise ValueError("invalid provider operation receipt status")
        if not isinstance(self.request_digest, str) or not _SHA256.fullmatch(self.request_digest):
            raise ValueError("request_digest must be a lowercase SHA-256 digest")
        _aware_timestamp(self.started_at, "started_at")
        if self.status == "in_progress":
            if self.result_digest is not None or self.completed_at is not None:
                raise ValueError("in-progress receipt cannot contain a result or completion time")
        else:
            if not isinstance(self.result_digest, str) or not _SHA256.fullmatch(self.result_digest):
                raise ValueError("completed receipt requires a lowercase result SHA-256 digest")
            _aware_timestamp(self.completed_at, "completed_at")
            if datetime.fromisoformat(self.completed_at.replace("Z", "+00:00")) < datetime.fromisoformat(
                self.started_at.replace("Z", "+00:00")
            ):
                raise ValueError("completed_at must not precede started_at")


@dataclass(frozen=True)
class DeploymentProviderOperationInspection:
    """Read-only aggregation of Host call receipts for one replacement operation.

    A terminal inspection means every recorded synchronous Host call returned.
    It does not claim that a provider has a durable operation resource or that
    current runtime/traffic state still matches the returned result.
    """

    provider: str
    project: str
    environment: str
    operation_id: str
    status: ProviderOperationInspectionStatus
    actions: tuple[DeploymentProviderOperationActionReceipt, ...]
    source_id: Literal["host-sqlite-operation-receipt-ledger"]
    completion_basis: Literal["host_call_return"]
    checked_at: str

    def __post_init__(self) -> None:
        for field in ("provider", "project", "environment", "operation_id"):
            _non_empty(getattr(self, field), field)
        if self.status not in {"not_found", "in_progress", "terminal", "unknown"}:
            raise ValueError("invalid provider operation inspection status")
        if not isinstance(self.actions, tuple) or any(
            not isinstance(item, DeploymentProviderOperationActionReceipt)
            for item in self.actions
        ):
            raise TypeError("actions must be a tuple of Host operation receipts")
        if len({item.action for item in self.actions}) != len(self.actions):
            raise ValueError("operation inspection contains duplicate actions")
        for item in self.actions:
            if (
                item.provider != self.provider
                or item.project != self.project
                or item.environment != self.environment
                or item.operation_id != self.operation_id
            ):
                raise ValueError("operation action receipt scope does not match inspection")
        if self.source_id != "host-sqlite-operation-receipt-ledger":
            raise ValueError("unsupported operation receipt source")
        if self.completion_basis != "host_call_return":
            raise ValueError("unsupported operation completion basis")
        _aware_timestamp(self.checked_at, "checked_at")
        expected = "not_found" if not self.actions else (
            "in_progress" if any(x.status == "in_progress" for x in self.actions) else (
                "unknown" if any(x.status == "unknown" for x in self.actions) else "terminal"
            )
        )
        if self.status != expected:
            raise ValueError("inspection status does not match its action receipts")

    def action_receipt(
        self, action: ProviderOperationAction
    ) -> DeploymentProviderOperationActionReceipt | None:
        """Return the exact action receipt, without inferring absent actions."""
        return next((item for item in self.actions if item.action == action), None)

    def action_succeeded(self, action: ProviderOperationAction) -> bool:
        receipt = self.action_receipt(action)
        return self.status == "terminal" and receipt is not None and receipt.status == "succeeded"


class HostDeploymentOperationReceiptInspector:
    """Expose the Host ledger as a scoped, read-only operation inspection source."""

    source_id = "host-sqlite-operation-receipt-ledger"

    def __init__(self, history, *, clock=None) -> None:
        if not callable(getattr(history, "list_provider_operation_receipts", None)):
            raise TypeError("history must expose list_provider_operation_receipts")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._history = history
        self._clock = clock or (lambda: datetime.now().astimezone().isoformat())

    def inspect_operation(
        self, *, provider: str, project: str, environment: str, operation_id: str
    ) -> DeploymentProviderOperationInspection:
        """Inspect only Host receipts bound to the complete replacement scope."""
        actions = self._history.list_provider_operation_receipts(
            provider=provider,
            project=project,
            environment=environment,
            operation_id=operation_id,
        )
        statuses = {item.status for item in actions}
        status: ProviderOperationInspectionStatus
        if not actions:
            status = "not_found"
        elif "in_progress" in statuses:
            status = "in_progress"
        elif "unknown" in statuses:
            status = "unknown"
        else:
            status = "terminal"
        checked_at = self._clock()
        return DeploymentProviderOperationInspection(
            provider=provider,
            project=project,
            environment=environment,
            operation_id=operation_id,
            status=status,
            actions=actions,
            source_id=self.source_id,
            completion_basis="host_call_return",
            checked_at=checked_at,
        )
