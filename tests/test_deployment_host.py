from __future__ import annotations

import json
import os
import sqlite3

import pytest

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_host import DeploymentHostRuntime
from runtime.deployment_provider import (
    DeploymentArtifact,
    DeploymentRecord,
)
from runtime.deployment_replacement import ReplacementJournalRecord
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider


class NoDockerCallsRunner:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append((list(args), cwd, timeout))
        raise AssertionError("startup recovery inventory must not invoke Docker")


def _record(deployment_id: str, *, status: str = "running") -> DeploymentRecord:
    artifact = DeploymentArtifact(
        "docker-local", f"image:{deployment_id}", "a" * 64, "1.0"
    )
    return DeploymentRecord(
        deployment_id,
        "docker-local",
        "staging",
        "1.0",
        artifact,
        status,
        "healthy",
        "2026-11-15T15:00:00Z",
        project="demo",
        container_id=("a" if deployment_id == "previous" else "b") * 64,
    )


def _seed_pending_replacement(path):
    history = DeploymentHistoryStore(path)
    previous = _record("previous")
    target = _record("candidate", status="prepared")
    history.append(previous)
    history.set_active_deployment(
        provider="docker-local",
        environment="staging",
        project="demo",
        deployment_id=previous.deployment_id,
        expected_deployment_id=None,
    )
    history.begin_replacement(
        ReplacementJournalRecord(
            operation_id="startup-operation-001",
            provider="docker-local",
            project="demo",
            environment="staging",
            target_deployment_id=target.deployment_id,
            previous_deployment_id=previous.deployment_id,
            phase="prepared",
            created_at="2026-11-15T15:01:00Z",
            updated_at="2026-11-15T15:01:00Z",
            previous_runtime_id=previous.container_id,
        )
    )
    return history


def test_host_runtime_creates_private_history_and_returns_empty_inventory(tmp_path):
    path = tmp_path / "private-state" / "deployments.sqlite3"

    result = DeploymentHostRuntime(path).start()

    assert path.is_file()
    assert result.history_path == str(path.resolve())
    assert result.provider == "docker-local"
    assert result.inventory == ()
    assert result.to_dict()["unfinished_replacements"] == 0
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_host_runtime_reads_pending_replacements_without_docker_calls(tmp_path):
    path = tmp_path / "host" / "deployments.sqlite3"
    _seed_pending_replacement(path)
    runner = NoDockerCallsRunner()

    result = DeploymentHostRuntime(
        path, provider=LocalDockerProvider(runner=runner)
    ).start()

    assert len(result.inventory) == 1
    assert result.inventory[0].operation_id == "startup-operation-001"
    assert result.inventory[0].classification == "prepared_candidate_not_persisted"
    assert result.inventory[0].external_state_verified is False
    assert result.inventory[0].automatic_recovery_allowed is False
    assert runner.calls == []
    assert result.to_dict()["inventory"][0]["recovery_assessment"]["automatic_action"] == "none"
    json.dumps(result.to_dict(), sort_keys=True)


def test_host_runtime_fails_closed_when_configured_database_is_corrupt(tmp_path):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a sqlite database")

    with pytest.raises(sqlite3.DatabaseError):
        DeploymentHostRuntime(path).start()
