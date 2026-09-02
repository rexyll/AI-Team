from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Mapping
from uuid import uuid4

from .sanitization import redact_secrets

MAX_OPERATION_HISTORY = 1000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MCPOperationRecord:
    """Bounded in-memory correlation record for one MCP capability invocation."""

    request_id: str
    operation_id: str
    capability: str
    policy_profile: str
    policy_allowed: bool
    started_at: str
    project_id: str | None = None
    execution_id: str | None = None
    finished_at: str | None = None
    duration_ms: float | None = None
    outcome: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": redact_secrets(self.request_id),
            "operation_id": redact_secrets(self.operation_id),
            "capability": redact_secrets(self.capability),
            "policy_profile": redact_secrets(self.policy_profile),
            "policy_allowed": self.policy_allowed,
            "started_at": self.started_at,
            "project_id": redact_secrets(self.project_id),
            "execution_id": redact_secrets(self.execution_id),
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "outcome": redact_secrets(self.outcome),
            "error_type": redact_secrets(self.error_type),
            "metadata": redact_secrets(self.metadata),
        }


class MCPOperationTracker:
    """Correlation and metrics adapter; not a durable audit store."""

    def __init__(self, *, max_records: int = MAX_OPERATION_HISTORY) -> None:
        if not isinstance(max_records, int) or isinstance(max_records, bool):
            raise TypeError("max_records must be an integer")
        if not 1 <= max_records <= MAX_OPERATION_HISTORY:
            raise ValueError(f"max_records must be between 1 and {MAX_OPERATION_HISTORY}")
        self._max_records = max_records
        self._records: dict[str, MCPOperationRecord] = {}
        self._order: list[str] = []
        self._lock = Lock()

    def start(
        self,
        capability: str,
        *,
        policy_profile: str,
        policy_allowed: bool,
        request_id: str | None = None,
        project_id: str | None = None,
        execution_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MCPOperationRecord:
        if not capability or not capability.strip():
            raise ValueError("capability must not be empty")
        record = MCPOperationRecord(
            request_id=request_id or str(uuid4()),
            operation_id=str(uuid4()),
            capability=capability,
            policy_profile=policy_profile,
            policy_allowed=bool(policy_allowed),
            started_at=_utc_now(),
            project_id=project_id,
            execution_id=execution_id,
            metadata=redact_secrets(dict(metadata or {})),
        )
        with self._lock:
            self._records[record.operation_id] = record
            self._order.append(record.operation_id)
            while len(self._order) > self._max_records:
                old_id = self._order.pop(0)
                self._records.pop(old_id, None)
        return record

    def finish(
        self,
        operation_id: str,
        *,
        outcome: str,
        error_type: str | None = None,
        execution_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MCPOperationRecord:
        with self._lock:
            record = self._records.get(operation_id)
            if record is None:
                raise KeyError(f"unknown MCP operation: {operation_id}")
            finished = datetime.now(timezone.utc)
            started = datetime.fromisoformat(record.started_at)
            record.finished_at = finished.isoformat()
            record.duration_ms = max(0.0, (finished - started).total_seconds() * 1000)
            record.outcome = outcome
            record.error_type = error_type
            if execution_id is not None:
                record.execution_id = execution_id
            if metadata:
                record.metadata.update(redact_secrets(metadata))
            return record

    def get(self, operation_id: str) -> MCPOperationRecord | None:
        with self._lock:
            return self._records.get(operation_id)

    def history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise TypeError("limit must be an integer")
        if not 1 <= limit <= self._max_records:
            raise ValueError(f"limit must be between 1 and {self._max_records}")
        with self._lock:
            ids = self._order[-limit:]
            return [self._records[item].as_dict() for item in reversed(ids)]
