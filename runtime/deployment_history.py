"""Host-owned persistent deployment history and rollback authorization.

The database is a host-private state store. Callers may request an environment
rollback, but cannot provide or override the historical DeploymentRecord used
as authority.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from runtime.deployment_provider import (
    DeploymentOperationResult,
    DeploymentRecord,
    DeploymentRequest,
    DeploymentProvider,
    HealthCheckResult,
    is_rollback_candidate,
)


def _record_to_json(record: DeploymentRecord) -> str:
    return json.dumps(asdict(record), sort_keys=True, separators=(",", ":"))


def _record_from_json(payload: str) -> DeploymentRecord:
    data = json.loads(payload)
    artifact = data.pop("artifact")
    from runtime.deployment_provider import DeploymentArtifact
    return DeploymentRecord(**data, artifact=DeploymentArtifact(**artifact))


class DeploymentHistoryStore:
    """SQLite-backed host history with transactional record replacement."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()
        # Deployment history can reveal project and release metadata. Restrict
        # the database file to the current host user on POSIX systems.
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 10000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS deployments (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    deployment_id TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    health_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )"""
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(deployments)")}
            if "project" not in columns:
                db.execute("ALTER TABLE deployments ADD COLUMN project TEXT")
            db.execute("DROP INDEX IF EXISTS idx_deployments_scope")
            db.execute(
                "CREATE INDEX idx_deployments_scope "
                "ON deployments(provider, environment, project, sequence DESC)"
            )
            result = db.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError("deployment history database integrity check failed")

    def append(self, record: DeploymentRecord) -> None:
        if record.status != "running":
            raise ValueError("only running deployment records can enter active history")
        with self._connect() as db:
            db.execute(
                """INSERT INTO deployments
                (deployment_id, provider, environment, project, status, health_status, created_at, record_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.deployment_id, record.provider, record.environment, record.project,
                    record.status, record.health_status, record.created_at,
                    _record_to_json(record),
                ),
            )

    def update_health(self, deployment_id: str, health: HealthCheckResult) -> DeploymentRecord:
        with self._connect() as db:
            row = db.execute(
                "SELECT record_json FROM deployments WHERE deployment_id = ?",
                (deployment_id,),
            ).fetchone()
            if row is None:
                raise KeyError("deployment is not present in host history")
            current = _record_from_json(row["record_json"])
            updated = replace(current, health_status=health.status)
            db.execute(
                """UPDATE deployments SET health_status = ?, record_json = ?
                WHERE deployment_id = ?""",
                (updated.health_status, _record_to_json(updated), deployment_id),
            )
            return updated

    def get(self, deployment_id: str) -> DeploymentRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT record_json FROM deployments WHERE deployment_id = ?",
                (deployment_id,),
            ).fetchone()
        return _record_from_json(row["record_json"]) if row else None

    def list_scope(self, provider: str, environment: str, project: str) -> list[DeploymentRecord]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT record_json FROM deployments
                WHERE provider = ? AND environment = ? AND project = ?
                ORDER BY sequence DESC""",
                (provider, environment, project),
            ).fetchall()
        return [_record_from_json(row["record_json"]) for row in rows]

    def rollback_candidate(
        self, *, provider: str, environment: str, project: str,
        excluding_deployment_id: str | None = None
    ) -> DeploymentRecord | None:
        for record in self.list_scope(provider, environment, project):
            if record.deployment_id == excluding_deployment_id:
                continue
            if is_rollback_candidate(record):
                return record
        return None


class HostDeploymentManager:
    """Host-only facade; Agent input never supplies rollback authority."""

    def __init__(self, provider: DeploymentProvider, history: DeploymentHistoryStore) -> None:
        if not isinstance(provider.name, str) or not provider.name.strip():
            raise ValueError("provider must expose a non-empty name")
        self.provider = provider
        self.history = history

    def record_deployment(self, result: DeploymentOperationResult) -> DeploymentRecord:
        if result.provider != self.provider.name:
            raise ValueError("deployment result provider does not match the configured host provider")
        if result.status != "succeeded" or result.record is None:
            raise ValueError("only successful deployment records from the configured provider may be persisted")
        if result.record.provider != self.provider.name or result.record.status != "running":
            raise ValueError("deployment record does not represent a running configured-provider deployment")
        self.history.append(result.record)
        return result.record

    def record_health(self, deployment_id: str, result: HealthCheckResult) -> DeploymentRecord:
        record = self.history.get(deployment_id)
        if record is None:
            raise KeyError("deployment is not present in host history")
        if record.provider != self.provider.name:
            raise ValueError("deployment provider does not match configured host provider")
        return self.history.update_health(deployment_id, result)

    def rollback(self, request: DeploymentRequest) -> DeploymentOperationResult:
        candidate = self.history.rollback_candidate(
            provider=self.provider.name, environment=request.environment, project=request.project
        )
        if candidate is None:
            return DeploymentOperationResult(
                "rollback", "failed", self.provider.name,
                "No prior verified healthy deployment exists in host history",
            )
        if candidate.artifact.provider != self.provider.name:
            return DeploymentOperationResult(
                "rollback", "failed", self.provider.name,
                "Historical artifact provider does not match configured host provider",
            )
        # Persisted health is only historical evidence. Re-check the immutable runtime
        # identity and health immediately before authorizing any replacement.
        try:
            fresh_health = self.provider.health_check(candidate)
        except Exception as exc:
            return DeploymentOperationResult(
                "rollback", "failed", self.provider.name,
                f"Fresh rollback health verification failed: {type(exc).__name__}",
            )
        try:
            self.history.update_health(candidate.deployment_id, fresh_health)
        except Exception as exc:
            return DeploymentOperationResult(
                "rollback", "failed", self.provider.name,
                f"Fresh rollback health could not be persisted: {type(exc).__name__}",
            )
        if fresh_health.status != "healthy":
            return DeploymentOperationResult(
                "rollback", "failed", self.provider.name,
                f"Rollback candidate is no longer verified healthy ({fresh_health.status})",
            )
        # The provider receives only the host-loaded record, never a caller record.
        return self.provider.rollback(request, candidate)
