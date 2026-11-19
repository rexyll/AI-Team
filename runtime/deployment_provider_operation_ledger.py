"""Durable Host receipts and read-only provider-operation inspection contracts.

The Host ledger records whether a synchronous provider method call returned.
It is not a provider-side operation API and must not be represented as proof
that an asynchronous external operation reached a terminal state. A row left
in "started" after a crash is indeterminate and is never promoted to success.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol

from runtime.deployment_provider import DeploymentOperationResult, OperationStatus

ProviderOperationInspectionStatus = Literal[
    "succeeded",
    "failed",
    "in_progress",
    "unknown",
    "not_found",
    "unavailable",
    "unsupported",
]
CallReceiptState = Literal["started", "returned", "indeterminate"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _timestamp(value: str, name: str) -> datetime:
    _required(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _canonical_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def provider_operation_request_digest(
    *,
    provider: str,
    project: str,
    environment: str,
    operation_id: str,
    operation_name: str,
    binding: Mapping[str, str],
) -> str:
    """Hash the exact Host scope/action binding without persisting request data."""
    for name, value in (
        ("provider", provider),
        ("project", project),
        ("environment", environment),
        ("operation_id", operation_id),
        ("operation_name", operation_name),
    ):
        _required(value, name)
    if not isinstance(binding, Mapping) or any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, str)
        for key, value in binding.items()
    ):
        raise ValueError("binding must map non-empty strings to strings")
    return _canonical_digest(
        {
            "provider": provider,
            "project": project,
            "environment": environment,
            "operation_id": operation_id,
            "operation_name": operation_name,
            "binding": dict(binding),
        }
    )


@dataclass(frozen=True)
class ProviderOperationInspection:
    """Authenticated provider-side inspection of one exact operation identity.

    A production inspector must query a provider-owned operation resource or
    documented operation-status API. It must not synthesize terminal status
    from a Host deployment journal or a Host call-return receipt.
    """

    provider: str
    project: str
    environment: str
    operation_id: str
    operation_name: str
    source_id: str
    status: ProviderOperationInspectionStatus
    inspected_at: str
    provider_operation_id: str | None = None
    response_digest_sha256: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "project",
            "environment",
            "operation_id",
            "operation_name",
            "source_id",
        ):
            _required(getattr(self, name), name)
        _timestamp(self.inspected_at, "inspected_at")
        if self.status not in {
            "succeeded", "failed", "in_progress", "unknown", "not_found",
            "unavailable", "unsupported",
        }:
            raise ValueError("invalid provider operation inspection status")
        if self.provider_operation_id is not None:
            _required(self.provider_operation_id, "provider_operation_id")
        if self.response_digest_sha256 is not None:
            _digest(self.response_digest_sha256, "response_digest_sha256")
        if self.status in {"succeeded", "failed", "in_progress"}:
            if self.provider_operation_id is None or self.response_digest_sha256 is None:
                raise ValueError(
                    "positive provider operation states require provider identity and response digest"
                )
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


class DeploymentProviderOperationInspector(Protocol):
    """Optional read-only provider capability for coordinator-operation lookup."""

    name: str

    def inspect_operation(
        self,
        *,
        project: str,
        environment: str,
        operation_id: str,
        operation_name: str,
    ) -> ProviderOperationInspection:
        """Return authenticated provider-side state for the exact operation."""
        ...


@dataclass(frozen=True)
class ProviderOperationCallReceipt:
    """Host's durable record of one provider method invocation lifecycle.

    "returned" means the synchronous method returned a structured result; it
    does not by itself prove asynchronous provider-side completion. "started"
    and "indeterminate" both mean the outcome cannot be concluded safely.
    """

    provider: str
    project: str
    environment: str
    operation_id: str
    operation_name: str
    request_digest_sha256: str
    state: CallReceiptState
    started_at: str
    completed_at: str | None = None
    provider_result_status: OperationStatus | None = None
    response_digest_sha256: str | None = None
    failure_kind: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "provider", "project", "environment", "operation_id", "operation_name"
        ):
            _required(getattr(self, name), name)
        _digest(self.request_digest_sha256, "request_digest_sha256")
        started = _timestamp(self.started_at, "started_at")
        if self.state not in {"started", "returned", "indeterminate"}:
            raise ValueError("invalid call receipt state")
        if self.completed_at is not None:
            completed = _timestamp(self.completed_at, "completed_at")
            if completed < started:
                raise ValueError("completed_at must not precede started_at")
        if self.response_digest_sha256 is not None:
            _digest(self.response_digest_sha256, "response_digest_sha256")
        if self.failure_kind is not None:
            _required(self.failure_kind, "failure_kind")
        if self.state == "started" and any(
            value is not None
            for value in (
                self.completed_at,
                self.provider_result_status,
                self.response_digest_sha256,
                self.failure_kind,
            )
        ):
            raise ValueError("started receipt cannot contain a terminal call result")
        if self.state == "returned":
            if (
                self.completed_at is None
                or self.provider_result_status not in {
                    "succeeded", "failed", "unavailable", "unsupported"
                }
                or self.response_digest_sha256 is None
                or self.failure_kind is not None
            ):
                raise ValueError("returned receipt requires a validated result and response digest")
        if self.state == "indeterminate" and (
            self.completed_at is None
            or self.provider_result_status is not None
            or self.response_digest_sha256 is not None
        ):
            raise ValueError("indeterminate receipt requires completion time but no provider result")


class DurableProviderOperationReceiptStore:
    """Separate SQLite ledger for Host-side provider call receipts.

    The ledger has its own file and primary key of provider scope + coordinator
    operation ID + action. A successful insert is fsynced by SQLite's durable
    transaction before the provider call is allowed to start. Duplicate calls
    are rejected rather than silently replayed.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        read_only: bool = False,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        if not isinstance(read_only, bool):
            raise TypeError("read_only must be a bool")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self.read_only = read_only
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if self.read_only:
            if not self.path.is_file():
                raise FileNotFoundError(f"operation receipt database not found: {self.path}")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._initialize()
            if os.name == "posix":
                os.chmod(self.path, 0o600)

    def _now(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Host clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            connection = sqlite3.connect(
                f"{self.path.as_uri()}?mode=ro", uri=True, timeout=10.0
            )
        else:
            connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        if not self.read_only:
            connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS provider_operation_call_receipts (
                    provider TEXT NOT NULL,
                    project TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    operation_name TEXT NOT NULL,
                    request_digest_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('started', 'returned', 'indeterminate')),
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    provider_result_status TEXT,
                    response_digest_sha256 TEXT,
                    failure_kind TEXT,
                    PRIMARY KEY (provider, project, environment, operation_id, operation_name)
                )"""
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError("provider operation receipt ledger integrity check failed")
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _scope(
        provider: str, project: str, environment: str, operation_id: str, operation_name: str
    ) -> tuple[str, str, str, str, str]:
        values = (provider, project, environment, operation_id, operation_name)
        for name, value in zip(
            ("provider", "project", "environment", "operation_id", "operation_name"), values
        ):
            _required(value, name)
        return values

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ProviderOperationCallReceipt:
        return ProviderOperationCallReceipt(
            provider=row["provider"],
            project=row["project"],
            environment=row["environment"],
            operation_id=row["operation_id"],
            operation_name=row["operation_name"],
            request_digest_sha256=row["request_digest_sha256"],
            state=row["state"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            provider_result_status=row["provider_result_status"],
            response_digest_sha256=row["response_digest_sha256"],
            failure_kind=row["failure_kind"],
        )

    def begin_operation(
        self,
        *,
        provider: str,
        project: str,
        environment: str,
        operation_id: str,
        operation_name: str,
        request_digest_sha256: str,
    ) -> ProviderOperationCallReceipt:
        if self.read_only:
            raise PermissionError("operation receipt store is read-only")
        scope = self._scope(provider, project, environment, operation_id, operation_name)
        _digest(request_digest_sha256, "request_digest_sha256")
        started_at = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO provider_operation_call_receipts (
                    provider, project, environment, operation_id, operation_name,
                    request_digest_sha256, state, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'started', ?)""",
                (*scope, request_digest_sha256, started_at),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ValueError("provider operation action already has a durable receipt") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        receipt = self.get_operation_receipt(
            provider=provider,
            project=project,
            environment=environment,
            operation_id=operation_id,
            operation_name=operation_name,
        )
        if receipt is None:
            raise RuntimeError("new provider operation receipt could not be read back")
        return receipt

    @staticmethod
    def _response_digest(
        result: DeploymentOperationResult,
    ) -> str:
        """Digest a bounded, secret-free projection of the returned result."""
        record = result.record
        artifact = result.artifact or (record.artifact if record is not None else None)
        payload: dict[str, object] = {
            "operation": result.operation,
            "provider": result.provider,
            "status": result.status,
            "message_sha256": hashlib.sha256(result.message.encode("utf-8")).hexdigest(),
            "artifact_digest": artifact.digest if artifact is not None else None,
            "record": (
                {
                    "deployment_id": record.deployment_id,
                    "status": record.status,
                    "container_id": record.container_id,
                    "artifact_digest": record.artifact.digest,
                }
                if record is not None
                else None
            ),
            "health_status": result.health.status if result.health is not None else None,
        }
        return _canonical_digest(payload)

    def record_result(
        self,
        *,
        provider: str,
        project: str,
        environment: str,
        operation_id: str,
        operation_name: str,
        result: DeploymentOperationResult,
    ) -> ProviderOperationCallReceipt:
        if self.read_only:
            raise PermissionError("operation receipt store is read-only")
        scope = self._scope(provider, project, environment, operation_id, operation_name)
        if not isinstance(result, DeploymentOperationResult):
            raise TypeError("result must be a DeploymentOperationResult")
        if result.provider != provider or result.operation != operation_name:
            raise ValueError("provider result identity does not match the receipt scope/action")
        completed_at = self._now()
        response_digest = self._response_digest(result)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """UPDATE provider_operation_call_receipts
                SET state = 'returned', completed_at = ?, provider_result_status = ?,
                    response_digest_sha256 = ?
                WHERE provider = ? AND project = ? AND environment = ?
                  AND operation_id = ? AND operation_name = ? AND state = 'started'""",
                (completed_at, result.status, response_digest, *scope),
            ).rowcount
            if changed != 1:
                connection.rollback()
                raise ValueError("provider operation receipt is absent or no longer started")
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        receipt = self.get_operation_receipt(
            provider=provider,
            project=project,
            environment=environment,
            operation_id=operation_id,
            operation_name=operation_name,
        )
        if receipt is None:
            raise RuntimeError("completed provider operation receipt could not be read back")
        return receipt

    def mark_indeterminate(
        self,
        *,
        provider: str,
        project: str,
        environment: str,
        operation_id: str,
        operation_name: str,
        failure_kind: str,
    ) -> ProviderOperationCallReceipt:
        if self.read_only:
            raise PermissionError("operation receipt store is read-only")
        scope = self._scope(provider, project, environment, operation_id, operation_name)
        _required(failure_kind, "failure_kind")
        completed_at = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """UPDATE provider_operation_call_receipts
                SET state = 'indeterminate', completed_at = ?, failure_kind = ?
                WHERE provider = ? AND project = ? AND environment = ?
                  AND operation_id = ? AND operation_name = ? AND state = 'started'""",
                (completed_at, failure_kind[:120], *scope),
            ).rowcount
            if changed != 1:
                connection.rollback()
                raise ValueError("provider operation receipt is absent or no longer started")
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        receipt = self.get_operation_receipt(
            provider=provider,
            project=project,
            environment=environment,
            operation_id=operation_id,
            operation_name=operation_name,
        )
        if receipt is None:
            raise RuntimeError("indeterminate provider operation receipt could not be read back")
        return receipt

    def get_operation_receipt(
        self,
        *,
        provider: str,
        project: str,
        environment: str,
        operation_id: str,
        operation_name: str,
    ) -> ProviderOperationCallReceipt | None:
        scope = self._scope(provider, project, environment, operation_id, operation_name)
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT * FROM provider_operation_call_receipts
                WHERE provider = ? AND project = ? AND environment = ?
                  AND operation_id = ? AND operation_name = ?""",
                scope,
            ).fetchone()
        finally:
            connection.close()
        return self._from_row(row) if row is not None else None

    def list_operation_receipts(
        self, *, provider: str, project: str, environment: str, operation_id: str
    ) -> tuple[ProviderOperationCallReceipt, ...]:
        for name, value in (
            ("provider", provider), ("project", project),
            ("environment", environment), ("operation_id", operation_id),
        ):
            _required(value, name)
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT * FROM provider_operation_call_receipts
                WHERE provider = ? AND project = ? AND environment = ? AND operation_id = ?
                ORDER BY operation_name""",
                (provider, project, environment, operation_id),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._from_row(row) for row in rows)
