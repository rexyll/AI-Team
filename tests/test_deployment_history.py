from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3

import pytest

from runtime.deployment_provider import (
    DeploymentArtifact, DeploymentOperationResult, DeploymentRecord,
    DeploymentRequest, HealthCheckResult,
)
from runtime.deployment_history import DeploymentHistoryStore, HostDeploymentManager
from runtime.deployment_replacement import ReplacementJournalRecord


class StubProvider:
    name = "docker-local"

    def __init__(self, result=None, health_result=None):
        self.result = result
        self.health_result = health_result or HealthCheckResult(
            "healthy", "2026-11-15T10:02:00Z", "stub health"
        )
        self.health_checked = []
        self.rollback_record = None

    def health_check(self, record):
        self.health_checked.append(record)
        return self.health_result

    def rollback(self, request, previous):
        self.rollback_record = previous
        return self.result or DeploymentOperationResult(
            "rollback", "unsupported", self.name, "safe replacement not implemented"
        )


def make_record(deployment_id, *, project="demo", environment="staging", status="running", health="healthy"):
    artifact = DeploymentArtifact("docker-local", f"image:{deployment_id}", "a" * 64, "1.0")
    return DeploymentRecord(
        deployment_id, "docker-local", environment, "1.0", artifact,
        status, health, "2026-11-15T10:00:00Z", project=project,
        container_id="c" * 64,
    )


def successful(record):
    return DeploymentOperationResult("deploy", "succeeded", "docker-local", "started", record=record)


def test_history_persists_and_reloads_records(tmp_path):
    db = tmp_path / "state" / "deployments.sqlite3"
    history = DeploymentHistoryStore(db)
    expected = make_record("old")
    history.append(expected)
    reloaded = DeploymentHistoryStore(db)
    assert reloaded.get("old") == expected


def test_history_persists_immutable_container_identity(tmp_path):
    db = tmp_path / "history.db"
    history = DeploymentHistoryStore(db)
    expected = make_record("immutable")
    history.append(expected)
    assert DeploymentHistoryStore(db).get("immutable").container_id == "c" * 64


def test_rollback_candidate_requires_immutable_container_identity(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    legacy = make_record("legacy")
    legacy = DeploymentRecord(
        legacy.deployment_id, legacy.provider, legacy.environment, legacy.version,
        legacy.artifact, legacy.status, legacy.health_status, legacy.created_at,
        project=legacy.project,
    )
    history.append(legacy)
    assert history.rollback_candidate(
        provider="docker-local", environment="staging", project="demo"
    ) is None


def test_history_rejects_non_running_records(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    with pytest.raises(ValueError, match="running"):
        history.append(make_record("stopped", status="stopped"))


def test_history_database_file_is_private_on_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX file mode assertion")
    db = tmp_path / "private" / "history.db"
    DeploymentHistoryStore(db)
    assert db.stat().st_mode & 0o777 == 0o600


def test_history_serializes_concurrent_appends(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    records = [make_record(f"parallel-{index}") for index in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(history.append, records))
    loaded = history.list_scope("docker-local", "staging", "demo")
    assert {record.deployment_id for record in loaded} == {
        record.deployment_id for record in records
    }


def test_corrupt_sqlite_database_fails_closed(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        DeploymentHistoryStore(db)


def test_corrupt_record_payload_fails_closed(tmp_path):
    db = tmp_path / "history.db"
    history = DeploymentHistoryStore(db)
    history.append(make_record("corrupt-record"))
    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE deployments SET record_json = ? WHERE deployment_id = ?",
            ("{invalid-json", "corrupt-record"),
        )
    with pytest.raises(ValueError):
        history.get("corrupt-record")


def test_only_verified_healthy_previous_record_is_candidate(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("unknown", health="unknown"))
    history.append(make_record("unhealthy", health="unhealthy"))
    history.append(make_record("healthy"))
    assert history.rollback_candidate(provider="docker-local", environment="staging", project="demo").deployment_id == "healthy"
    assert history.rollback_candidate(provider="docker-local", environment="staging", project="other") is None
    assert history.rollback_candidate(provider="docker-local", environment="production", project="demo") is None


def test_health_observation_updates_persisted_record(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("deploy", health="unknown"))
    updated = history.update_health(
        "deploy", HealthCheckResult("healthy", "2026-11-15T10:01:00Z", "docker healthcheck")
    )
    assert updated.health_status == "healthy"
    assert DeploymentHistoryStore(tmp_path / "history.db").get("deploy").health_status == "healthy"


def test_manager_persists_only_success_from_configured_provider(tmp_path):
    provider = StubProvider()
    manager = HostDeploymentManager(provider, DeploymentHistoryStore(tmp_path / "history.db"))
    record = make_record("deploy")
    assert manager.record_deployment(successful(record)) == record
    with pytest.raises(ValueError, match="successful"):
        manager.record_deployment(DeploymentOperationResult("deploy", "failed", provider.name, "no"))
    foreign_artifact = DeploymentArtifact("other", "image:foreign", "b" * 64, "1.0")
    foreign_record = DeploymentRecord(
        "foreign", "other", "staging", "1.0", foreign_artifact,
        "running", "healthy", "2026-11-15T10:00:00Z",
    )
    with pytest.raises(ValueError, match="configured"):
        manager.record_deployment(
            DeploymentOperationResult("deploy", "succeeded", "other", "wrong", record=foreign_record)
        )
    assert manager.history.get("foreign") is None


def test_manager_rollback_rechecks_health_before_provider_call(tmp_path):
    provider = StubProvider()
    history = DeploymentHistoryStore(tmp_path / "history.db")
    old = make_record("old")
    history.append(old)
    manager = HostDeploymentManager(provider, history)
    result = manager.rollback(DeploymentRequest("/tmp", "demo", "staging", "2.0"))
    assert result.status == "unsupported"
    assert provider.health_checked == [old]
    assert provider.rollback_record == old
    assert history.get("old").health_status == "healthy"


@pytest.mark.parametrize("status", ["unhealthy", "unavailable", "unknown"])
def test_manager_blocks_rollback_when_fresh_health_is_not_healthy(tmp_path, status):
    provider = StubProvider(health_result=HealthCheckResult(
        status, "2026-11-15T10:03:00Z", "fresh health"
    ))
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("old"))
    manager = HostDeploymentManager(provider, history)
    result = manager.rollback(DeploymentRequest("/tmp", "demo", "staging", "2.0"))
    assert result.status == "failed"
    assert "no longer verified healthy" in result.message
    assert provider.health_checked
    assert provider.rollback_record is None
    assert history.get("old").health_status == status


def test_manager_blocks_rollback_when_fresh_health_check_raises(tmp_path):
    class RaisingProvider(StubProvider):
        def health_check(self, record):
            raise OSError("daemon unavailable")

    provider = RaisingProvider()
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("old"))
    manager = HostDeploymentManager(provider, history)
    result = manager.rollback(DeploymentRequest("/tmp", "demo", "staging", "2.0"))
    assert result.status == "failed"
    assert "OSError" in result.message
    assert provider.rollback_record is None
    assert history.get("old").health_status == "healthy"


def test_manager_blocks_rollback_when_fresh_health_cannot_be_persisted(tmp_path):
    provider = StubProvider()
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("old"))
    manager = HostDeploymentManager(provider, history)

    def fail_update(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    history.update_health = fail_update
    result = manager.rollback(DeploymentRequest("/tmp", "demo", "staging", "2.0"))
    assert result.status == "failed"
    assert "could not be persisted" in result.message
    assert provider.rollback_record is None


def test_manager_fails_closed_without_prior_healthy_deployment(tmp_path):
    provider = StubProvider()
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("not-healthy", health="unknown"))
    manager = HostDeploymentManager(provider, history)
    result = manager.rollback(DeploymentRequest("/tmp", "demo", "staging", "2.0"))
    assert result.status == "failed"
    assert provider.rollback_record is None


def test_active_deployment_is_explicit_and_not_inferred_from_history(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("old"))
    assert history.active_deployment(
        provider="docker-local", environment="staging", project="demo"
    ) is None


def test_active_deployment_compare_and_swap_switches_one_scope(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    old, new = make_record("old"), make_record("new")
    history.append(old)
    history.append(new)
    assert history.set_active_deployment(
        provider="docker-local", environment="staging", project="demo",
        deployment_id="old", expected_deployment_id=None,
    ) == old
    with pytest.raises(ValueError, match="compare-and-swap"):
        history.set_active_deployment(
            provider="docker-local", environment="staging", project="demo",
            deployment_id="new", expected_deployment_id=None,
        )
    assert history.active_deployment(
        provider="docker-local", environment="staging", project="demo"
    ) == old
    assert history.set_active_deployment(
        provider="docker-local", environment="staging", project="demo",
        deployment_id="new", expected_deployment_id="old",
    ) == new
    assert history.active_deployment(
        provider="docker-local", environment="staging", project="demo"
    ) == new


def test_active_deployment_rejects_wrong_scope_and_non_running_record(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("other-project", project="other"))
    with pytest.raises(ValueError, match="running"):
        history.append(make_record("stopped", status="stopped"))
    with pytest.raises(ValueError, match="exact requested scope"):
        history.set_active_deployment(
            provider="docker-local", environment="staging", project="demo",
            deployment_id="other-project", expected_deployment_id=None,
        )


def test_active_deployment_pointer_is_scoped_to_record_identity(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("one"))
    history.set_active_deployment(
        provider="docker-local", environment="staging", project="demo",
        deployment_id="one", expected_deployment_id=None,
    )
    assert history.active_deployment(
        provider="docker-local", environment="production", project="demo"
    ) is None
    with pytest.raises(ValueError, match="exact requested scope"):
        history.set_active_deployment(
            provider="docker-local", environment="production", project="demo",
            deployment_id="one", expected_deployment_id=None,
        )


def test_active_deployment_clear_requires_matching_identity(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.append(make_record("active"))
    history.set_active_deployment(
        provider="docker-local", environment="staging", project="demo",
        deployment_id="active", expected_deployment_id=None,
    )
    with pytest.raises(ValueError, match="clear compare-and-swap"):
        history.clear_active_deployment(
            provider="docker-local", environment="staging", project="demo",
            expected_deployment_id="stale",
        )
    history.clear_active_deployment(
        provider="docker-local", environment="staging", project="demo",
        expected_deployment_id="active",
    )
    assert history.active_deployment(
        provider="docker-local", environment="staging", project="demo"
    ) is None

def make_replacement(**overrides):
    values = {
        "operation_id": "replace-001", "provider": "docker-local",
        "project": "demo", "environment": "staging",
        "target_deployment_id": "release-target",
        "previous_deployment_id": "release-current", "phase": "prepared",
        "created_at": "2026-11-15T10:00:00Z",
        "updated_at": "2026-11-15T10:00:00Z",
    }
    values.update(overrides)
    return ReplacementJournalRecord(**values)


def test_replacement_journal_persists_and_reloads(tmp_path):
    path = tmp_path / "history.db"
    history = DeploymentHistoryStore(path)
    record = make_replacement()
    history.begin_replacement(record)
    assert DeploymentHistoryStore(path).get_replacement(record.operation_id) == record


def test_replacement_journal_requires_prepared_initial_phase(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    with pytest.raises(ValueError, match="prepared"):
        history.begin_replacement(make_replacement(phase="candidate_started"))


def test_replacement_journal_reserves_one_nonterminal_scope(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    history.begin_replacement(make_replacement())
    with pytest.raises(ValueError, match="scope is reserved"):
        history.begin_replacement(make_replacement(operation_id="replace-002"))
    history.begin_replacement(make_replacement(operation_id="replace-other", project="other"))


def test_replacement_journal_phase_update_uses_cas_and_reloads(tmp_path):
    path = tmp_path / "history.db"
    history = DeploymentHistoryStore(path)
    initial = make_replacement()
    history.begin_replacement(initial)
    started = make_replacement(phase="candidate_started", updated_at="2026-11-15T10:01:00Z",
                               candidate_runtime_id="runtime-candidate")
    history.update_replacement(started, expected_phase="prepared")
    with pytest.raises(ValueError, match="compare-and-swap"):
        history.update_replacement(started, expected_phase="prepared")
    assert DeploymentHistoryStore(path).get_replacement(initial.operation_id) == started


def test_replacement_journal_rejects_immutable_identity_rewrite(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    initial = make_replacement()
    history.begin_replacement(initial)
    changed = make_replacement(phase="candidate_started", target_deployment_id="tampered")
    with pytest.raises(ValueError, match="immutable identity"):
        history.update_replacement(changed, expected_phase="prepared")


def test_replacement_journal_runtime_identity_is_immutable_once_set(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    initial = make_replacement()
    history.begin_replacement(initial)
    started = make_replacement(phase="candidate_started", candidate_runtime_id="runtime-1")
    history.update_replacement(started, expected_phase="prepared")
    changed = make_replacement(phase="candidate_healthy", candidate_runtime_id="runtime-2")
    with pytest.raises(ValueError, match="immutable candidate_runtime_id"):
        history.update_replacement(changed, expected_phase="candidate_started")


def test_replacement_journal_terminal_phase_releases_scope_reservation(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    initial = make_replacement()
    history.begin_replacement(initial)
    aborted = make_replacement(phase="aborted", updated_at="2026-11-15T10:01:00Z")
    history.update_replacement(aborted, expected_phase="prepared")
    history.begin_replacement(make_replacement(operation_id="replace-next"))


def test_needs_reconciliation_keeps_scope_reserved(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    initial = make_replacement()
    history.begin_replacement(initial)
    blocked = make_replacement(phase="needs_reconciliation")
    history.update_replacement(blocked, expected_phase="prepared")
    assert [r.phase for r in history.list_active_replacements()] == ["needs_reconciliation"]
    with pytest.raises(ValueError, match="scope is reserved"):
        history.begin_replacement(make_replacement(operation_id="replace-next"))


def test_replacement_journal_rejects_invalid_phase_transition(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    initial = make_replacement()
    history.begin_replacement(initial)
    invalid = make_replacement(phase="traffic_switched")
    with pytest.raises(ValueError, match="phase transition"):
        history.update_replacement(invalid, expected_phase="prepared")
