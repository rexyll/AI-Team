from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import sqlite3

import pytest

from runtime.deployment_provider import (
    DeploymentArtifact, DeploymentOperationResult, DeploymentRecord,
    DeploymentRequest, HealthCheckResult,
)
from runtime.deployment_history import DeploymentHistoryStore, HostDeploymentManager
from runtime.local_docker_router_state import LocalDockerRouterStateStore
from runtime.local_docker_router_network import build_router_network_spec
from runtime.deployment_replacement import ReplacementJournalRecord
from runtime.deployment_traffic_router import (
    TrafficPortBinding,
    TrafficRouteTarget,
    TrafficRouterRecord,
    TrafficRouterScope,
)


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



def test_read_only_history_store_requires_existing_db_and_rejects_writes(tmp_path):
    path = tmp_path / "readonly" / "history.db"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        DeploymentHistoryStore(path, read_only=True)
    assert not path.exists()

    DeploymentHistoryStore(path)
    readonly = DeploymentHistoryStore(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.append(make_record("must-not-write"))


def make_traffic_router_state_record(
    tmp_path, *, project="demo", port_bindings=None, active_slot=None
):
    scope = TrafficRouterScope("docker-local", project, "staging")
    ports = port_bindings or (
        TrafficPortBinding(8080, 80),
        TrafficPortBinding(8443, 443),
    )
    result = LocalDockerRouterStateStore(tmp_path / f"state-{project}").persist(
        scope, ports, active_slot=None
    )
    assert result.status == "persisted"
    record = result.record
    if active_slot is not None:
        updated = LocalDockerRouterStateStore(
            tmp_path / f"state-{project}"
        ).persist_active_slot_map(
            record, expected_active_slot=None, active_slot=active_slot
        )
        assert updated.status == "persisted"
        record = updated.record
    return record


def make_traffic_router_record(*, active_slot=None, active_target=None, generation="gen-0", project="demo"):
    scope = TrafficRouterScope("docker-local", project, "staging")
    ports = (TrafficPortBinding(8080, 80), TrafficPortBinding(8443, 443))
    return TrafficRouterRecord(
        scope=scope,
        router_deployment_id=f"router-{project}",
        router_runtime_id="b" * 64,
        network_name=build_router_network_spec(scope).network_name,
        network_id="c" * 64,
        port_bindings=ports,
        active_slot=active_slot,
        active_target=active_target,
        route_generation=generation,
        created_at="2026-11-17T10:00:00Z",
    )


def test_traffic_router_registry_persists_and_reloads_durable_scope_record(tmp_path):
    path = tmp_path / "history.db"
    history = DeploymentHistoryStore(path)
    record = make_traffic_router_record()
    state_record = make_traffic_router_state_record(tmp_path)
    assert history.create_traffic_router(record, state_record) == record
    reloaded_history = DeploymentHistoryStore(path)
    reloaded = reloaded_history.get_traffic_router(record.scope)
    assert reloaded == record
    assert reloaded_history.get_traffic_router_state_record(record.scope) == state_record


def test_traffic_router_registry_is_scope_isolated_and_rejects_duplicate_create(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    first = make_traffic_router_record()
    other = make_traffic_router_record(project="other")
    history.create_traffic_router(first, make_traffic_router_state_record(tmp_path, project="demo"))
    history.create_traffic_router(other, make_traffic_router_state_record(tmp_path, project="other"))
    assert history.get_traffic_router(first.scope) == first
    assert history.get_traffic_router(other.scope) == other
    assert history.get_traffic_router_state_record(first.scope) is not None
    with pytest.raises(ValueError, match="already has a durable record"):
        history.create_traffic_router(first, make_traffic_router_state_record(tmp_path, project="demo"))


def test_traffic_router_registry_route_update_uses_generation_cas(tmp_path):
    path = tmp_path / "history.db"
    history = DeploymentHistoryStore(path)
    initial = make_traffic_router_record()
    state_initial = make_traffic_router_state_record(tmp_path)
    history.create_traffic_router(initial, state_initial)
    target = TrafficRouteTarget(
        "release-2", "d" * 64, "172.18.0.9", initial.port_bindings
    )
    updated = replace(
        initial,
        active_slot="slot_b",
        active_target=target,
        slot_targets=(("slot_b", target),),
        route_generation="gen-1",
    )
    state_next = make_traffic_router_state_record(
        tmp_path, active_slot="slot_b"
    )
    assert history.update_traffic_router(
        updated,
        state_next,
        expected_generation="gen-0",
        expected_state_map_sha256=state_initial.active_slot_map_sha256,
    ) == updated
    reloaded_history = DeploymentHistoryStore(path)
    assert reloaded_history.get_traffic_router(initial.scope) == updated
    assert reloaded_history.get_traffic_router_state_record(initial.scope) == state_next
    with pytest.raises(ValueError, match="generation compare-and-swap"):
        history.update_traffic_router(
            replace(updated, route_generation="gen-2"),
            state_next,
            expected_generation="gen-0",
            expected_state_map_sha256=state_next.active_slot_map_sha256,
        )
    assert history.get_traffic_router(initial.scope) == updated


def test_traffic_router_registry_rejects_router_identity_and_port_rewrite(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    initial = make_traffic_router_record()
    state_record = make_traffic_router_state_record(tmp_path)
    history.create_traffic_router(initial, state_record)
    with pytest.raises(ValueError, match="immutable identity rewrite"):
        history.update_traffic_router(
            replace(initial, router_runtime_id="e" * 64, route_generation="gen-1"),
            state_record,
            expected_generation="gen-0",
            expected_state_map_sha256=state_record.active_slot_map_sha256,
        )
    with pytest.raises(ValueError, match="immutable identity rewrite"):
        history.update_traffic_router(
            replace(
                initial,
                port_bindings=(TrafficPortBinding(8081, 80),),
                route_generation="gen-1",
            ),
            state_record,
            expected_generation="gen-0",
            expected_state_map_sha256=state_record.active_slot_map_sha256,
        )


def test_traffic_router_registry_rejects_initial_active_target(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    ports = (TrafficPortBinding(8080, 80),)
    target = TrafficRouteTarget("release-1", "d" * 64, "172.18.0.9", ports)
    record = TrafficRouterRecord(
        scope=TrafficRouterScope("docker-local", "demo", "staging"),
        router_deployment_id="router-demo",
        router_runtime_id="b" * 64,
        network_name="ai-team-router-" + "c" * 20,
        port_bindings=ports,
        active_slot="slot_a",
        active_target=target,
        route_generation="gen-0",
        created_at="2026-11-17T10:00:00Z",
    )
    with pytest.raises(ValueError, match="start with no active"):
        history.create_traffic_router(
            record,
            make_traffic_router_state_record(
                tmp_path, port_bindings=ports, active_slot="slot_a"
            ),
        )


def test_traffic_router_registry_fails_closed_on_corrupt_json(tmp_path):
    path = tmp_path / "history.db"
    history = DeploymentHistoryStore(path)
    record = make_traffic_router_record()
    history.create_traffic_router(
        record, make_traffic_router_state_record(tmp_path)
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE traffic_routers SET record_json = ? WHERE provider = ? AND project = ? AND environment = ?",
            ("{bad-json", "docker-local", "demo", "staging"),
        )
    with pytest.raises(ValueError):
        DeploymentHistoryStore(path).get_traffic_router(record.scope)


def test_traffic_router_registry_read_only_store_can_load_but_not_mutate(tmp_path):
    path = tmp_path / "history.db"
    history = DeploymentHistoryStore(path)
    record = make_traffic_router_record()
    history.create_traffic_router(
        record, make_traffic_router_state_record(tmp_path)
    )
    readonly = DeploymentHistoryStore(path, read_only=True)
    assert readonly.get_traffic_router(record.scope) == record
    assert readonly.get_traffic_router_state_record(record.scope) is not None
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.create_traffic_router(
            make_traffic_router_record(project="other"),
            make_traffic_router_state_record(tmp_path, project="other"),
        )


def test_traffic_router_registry_requires_immutable_network_id_and_scope_name(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    record = make_traffic_router_record()
    state_record = make_traffic_router_state_record(tmp_path)
    with pytest.raises(ValueError, match="immutable network identity"):
        history.create_traffic_router(
            replace(record, network_id=None), state_record
        )
    with pytest.raises(ValueError, match="immutable network identity"):
        history.create_traffic_router(
            replace(record, network_name="ai-team-router-" + "f" * 20),
            state_record,
        )


def test_traffic_router_registry_persists_slot_targets_and_checks_active_target(tmp_path):
    path = tmp_path / "history.db"
    history = DeploymentHistoryStore(path)
    record = make_traffic_router_record()
    state_record = make_traffic_router_state_record(tmp_path)
    target_a = TrafficRouteTarget(
        "release-a", "d" * 64, "172.18.0.10", record.port_bindings
    )
    target_b = TrafficRouteTarget(
        "release-b", "e" * 64, "172.18.0.11", record.port_bindings
    )
    updated = replace(
        record,
        active_slot="slot_b",
        active_target=target_b,
        slot_targets=(("slot_a", target_a), ("slot_b", target_b)),
        route_generation="gen-1",
    )
    changed_state = make_traffic_router_state_record(
        tmp_path, active_slot="slot_b"
    )
    history.create_traffic_router(record, state_record)
    history.update_traffic_router(
        updated,
        changed_state,
        expected_generation="gen-0",
        expected_state_map_sha256=state_record.active_slot_map_sha256,
    )
    loaded = DeploymentHistoryStore(path).get_traffic_router(record.scope)
    assert loaded == updated
    assert dict(loaded.slot_targets)["slot_a"] == target_a
    assert dict(loaded.slot_targets)["slot_b"] == target_b


def test_traffic_router_registry_rejects_active_target_conflicting_with_slot_inventory(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    initial = make_traffic_router_record()
    state_record = make_traffic_router_state_record(tmp_path)
    target_a = TrafficRouteTarget(
        "release-a", "d" * 64, "172.18.0.10", initial.port_bindings
    )
    target_b = TrafficRouteTarget(
        "release-b", "e" * 64, "172.18.0.11", initial.port_bindings
    )
    conflict = replace(
        initial,
        active_slot="slot_b",
        active_target=target_b,
        slot_targets=(("slot_b", target_a),),
        route_generation="gen-1",
    )
    with pytest.raises(ValueError, match="active_target must match"):
        history.create_traffic_router(conflict, state_record)
