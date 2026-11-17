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



def test_standalone_read_only_inventory_does_not_create_missing_database(tmp_path):
    path = tmp_path / "missing" / "deployments.sqlite3"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        DeploymentHostRuntime(path, create_if_missing=False).start()

    assert not path.exists()


def test_host_runtime_uses_read_only_sqlite_for_existing_database(tmp_path):
    path = tmp_path / "host" / "deployments.sqlite3"
    _seed_pending_replacement(path)

    result = DeploymentHostRuntime(path).start()

    assert len(result.inventory) == 1
    readonly = DeploymentHistoryStore(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.append(_record("must-not-write"))


def test_host_runtime_inspects_recorded_runtime_by_immutable_id_without_route_claim(tmp_path):
    path = tmp_path / "host" / "deployments.sqlite3"
    _seed_pending_replacement(path)

    class InspectRunner:
        def __init__(self):
            self.calls = []

        def execute(self, args, *, cwd, timeout):
            self.calls.append((list(args), cwd, timeout))
            return DockerCommandResult(
                0,
                "a" * 64 + "|running|healthy",
                "",
            )

    runner = InspectRunner()
    report = DeploymentHostRuntime(
        path,
        provider=LocalDockerProvider(runner=runner),
    ).inspect_recovery()

    assert report["unfinished_replacements"] == 1
    observation = report["observations"][0]
    assert observation["operation_id"] == "startup-operation-001"
    assert observation["previous_runtime"]["status"] == "verified"
    assert observation["previous_runtime"]["health_status"] == "healthy"
    assert observation["candidate_runtime"] is None
    assert observation["route_readback_status"] == "not_available"
    assert observation["automatic_recovery_allowed"] is False
    assert report["route_readback_available"] is False
    assert report["automatic_recovery_allowed"] is False
    assert runner.calls[0][0] == ["inspect", "--format", "{{.Id}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", "a" * 64]


def test_host_runtime_reports_daemon_unavailable_without_authorizing_recovery(tmp_path):
    path = tmp_path / "host" / "deployments.sqlite3"
    _seed_pending_replacement(path)

    class UnavailableRunner:
        def execute(self, args, *, cwd, timeout):
            return DockerCommandResult(1, "", "Cannot connect to the Docker daemon")

    report = DeploymentHostRuntime(
        path,
        provider=LocalDockerProvider(runner=UnavailableRunner()),
    ).inspect_recovery()

    previous = report["observations"][0]["previous_runtime"]
    assert previous["status"] == "unavailable"
    assert report["route_readback_available"] is False
    assert report["automatic_recovery_allowed"] is False


def test_host_runtime_inspects_journal_candidate_id_when_candidate_record_is_missing(tmp_path):
    path = tmp_path / "host" / "deployments.sqlite3"
    history = _seed_pending_replacement(path)
    prepared = history.get_replacement("startup-operation-001")
    started = ReplacementJournalRecord(
        operation_id=prepared.operation_id,
        provider=prepared.provider,
        project=prepared.project,
        environment=prepared.environment,
        target_deployment_id=prepared.target_deployment_id,
        previous_deployment_id=prepared.previous_deployment_id,
        phase="candidate_started",
        created_at=prepared.created_at,
        updated_at="2026-11-15T16:10:00Z",
        previous_runtime_id=prepared.previous_runtime_id,
        candidate_runtime_id="b" * 64,
    )
    history.update_replacement(started, expected_phase="prepared")

    class InspectRunner:
        def __init__(self):
            self.calls = []

        def execute(self, args, *, cwd, timeout):
            self.calls.append((list(args), cwd, timeout))
            runtime_id = args[-1]
            return DockerCommandResult(
                0,
                runtime_id + "|running|none",
                "",
            )

    runner = InspectRunner()
    report = DeploymentHostRuntime(
        path, provider=LocalDockerProvider(runner=runner)
    ).inspect_recovery()
    observation = report["observations"][0]

    assert observation["candidate_record_present"] is False
    assert observation["candidate_runtime"]["status"] == "verified"
    assert observation["candidate_runtime"]["expected_runtime_id"] == "b" * 64
    assert observation["candidate_runtime"]["health_status"] == "unknown"
    assert observation["automatic_recovery_allowed"] is False
    assert report["route_readback_available"] is False
    assert len(runner.calls) == 2
    assert runner.calls[1][0][-1] == "b" * 64
