from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.local_docker_router_host import LocalDockerRouterHostManager
from runtime.local_docker_router_image import (
    DockerRouterImageIdentity,
    ROUTER_BASE_IMAGE_REF,
    ROUTER_HAPROXY_VERSION,
    ROUTER_SOCAT_PACKAGE_VERSION,
)
from runtime.local_docker_router_network import (
    DockerRouterNetworkRecord,
    build_router_network_spec,
)


class Runner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append(list(args))
        return self.result


def _scope():
    return TrafficRouterScope("docker-local", "host-manager", "test")


def _bindings():
    return (TrafficPortBinding(18080, 80), TrafficPortBinding(18443, 443))


def _network(scope):
    spec = build_router_network_spec(scope)
    return DockerRouterNetworkRecord(
        spec.network_name, "b" * 64, spec.scope_fingerprint,
        "bridge", False, False,
    )


def _image():
    return DockerRouterImageIdentity(
        "sha256:" + "a" * 64, "linux", "amd64",
        ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION,
        ROUTER_BASE_IMAGE_REF, "1",
    )


def _manager(tmp_path):
    runner = Runner(DockerCommandResult(1, "", "Error: No such container: ai-team-router"))
    provider = LocalDockerProvider(runner)
    history = DeploymentHistoryStore(tmp_path / "history.db")
    manager = LocalDockerRouterHostManager(
        provider, history, tmp_path / "repo", tmp_path / "router-state"
    )
    return manager, history, runner


def _patch_new_managers(monkeypatch, manager, scope, *, router_id="c" * 64):
    network = _network(scope)
    image = _image()
    monkeypatch.setattr(
        manager.network_manager,
        "ensure_network",
        lambda requested: SimpleNamespace(
            status="created", record=network, detail=""
        ),
    )
    monkeypatch.setattr(
        manager.image_manager,
        "build_and_verify",
        lambda: SimpleNamespace(
            status="verified", identity=image, detail=""
        ),
    )
    monkeypatch.setattr(
        manager.config_validator,
        "validate",
        lambda image_arg, state_arg, *, expected_active_slot=None: SimpleNamespace(
            status="valid", detail=""
        ),
    )
    monkeypatch.setattr(
        manager.container_manager,
        "ensure_router",
        lambda spec: SimpleNamespace(
            status="created", container_id=router_id, detail=""
        ),
    )


def _register_existing(tmp_path, history, scope, bindings, *, active_slot=None):
    from runtime.local_docker_router_state import LocalDockerRouterStateStore
    from runtime.deployment_traffic_router import TrafficRouterRecord, TrafficRouteTarget

    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    initial = store.persist(scope, bindings)
    assert initial.status == "persisted"
    state = initial.record
    if active_slot is not None:
        server_state = store.persist_servers_state(
            state, bindings, _server_state_snapshot_for_test(bindings)
        )
        assert server_state.status == "persisted"
        state = server_state.record
    network = _network(scope)
    spec = build_router_network_spec(scope)
    record = TrafficRouterRecord(
        scope=scope,
        router_deployment_id="router-" + spec.scope_fingerprint[:20],
        router_runtime_id="c" * 64,
        network_name=network.network_name,
        network_id=network.network_id,
        port_bindings=bindings,
        active_slot=None,
        active_target=None,
        route_generation="generation-0",
        created_at="2026-11-17T12:00:00Z",
        slot_targets=(),
    )
    history.create_traffic_router(record, state)
    if active_slot is not None:
        target = TrafficRouteTarget("release", "d" * 64, "172.18.0.9", bindings)
        slots = ((active_slot, target),)
        switched = store.persist_active_slot_map(
            state, expected_active_slot=None, active_slot=active_slot
        )
        assert switched.status == "persisted"
        updated_record = replace(
            record,
            active_slot=active_slot,
            active_target=target,
            slot_targets=slots,
            route_generation="generation-1",
        )
        history.update_traffic_router(
            updated_record,
            switched.record,
            expected_generation="generation-0",
            expected_state_map_sha256=state.active_slot_map_sha256,
        )
        record = updated_record
        state = switched.record
    return record, state, network


def _server_state_snapshot_for_test(bindings):
    header = (
        "# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state "
        "srv_uweight srv_iweight srv_time_since_last_change srv_check_status "
        "srv_check_result srv_check_health srv_check_state srv_agent_state "
        "bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl "
        "srv_check_port srv_check_addr srv_agent_addr srv_agent_port"
    )
    rows = []
    for index, binding in enumerate(bindings, start=1):
        for server_id, server in enumerate(("slot_a", "slot_b"), start=1):
            rows.append(
                f"{index} be_p{binding.host_port} {server_id} {server} 127.0.0.1 0 0 "
                f"0 0 0 6 0 0 6 0 0 0 - {binding.container_port} - 0 "
                f"{binding.container_port} 127.0.0.1 - 0"
            )
    return "1\n" + header + "\n" + "\n".join(rows) + "\n"


def test_initial_scope_create_commits_router_and_digest_bound_host_state(tmp_path, monkeypatch):
    manager, history, runner = _manager(tmp_path)
    scope = _scope()
    _patch_new_managers(monkeypatch, manager, scope)

    result = manager.ensure_router(scope, _bindings())

    assert result.status == "created"
    assert result.router_record is not None
    assert result.router_record.network_id == "b" * 64
    assert result.router_record.router_runtime_id == "c" * 64
    assert result.router_record.active_slot is None
    assert result.state_record is not None
    assert history.get_traffic_router(scope) == result.router_record
    assert history.get_traffic_router_state_record(scope) == result.state_record
    assert runner.calls == [["container", "inspect", "--format", "{{.Id}}", f"ai-team-router-c-{result.router_record.network_name[-20:]}"]]


def test_existing_scope_reload_accepts_durable_active_selector_without_rewriting_it(tmp_path, monkeypatch):
    manager, history, _ = _manager(tmp_path)
    scope = _scope()
    record, state, network = _register_existing(
        tmp_path, history, scope, _bindings(), active_slot="slot_b"
    )
    image = _image()
    observed = {}

    monkeypatch.setattr(
        manager.network_manager,
        "_inspect",
        lambda spec: ("verified", network, ""),
    )
    monkeypatch.setattr(
        manager,
        "_inspect_router_image_id",
        lambda runtime_id: ("verified", image.image_id, ""),
    )
    monkeypatch.setattr(
        manager.image_manager,
        "inspect_image",
        lambda image_id: SimpleNamespace(status="verified", identity=image, detail=""),
    )
    monkeypatch.setattr(
        manager.image_manager,
        "build_and_verify",
        lambda: pytest.fail("existing Router reload must not rebuild its image"),
    )
    def validate(image_arg, state_arg, *, expected_active_slot=None):
        observed["expected_active_slot"] = expected_active_slot
        return SimpleNamespace(status="valid", detail="")
    monkeypatch.setattr(manager.config_validator, "validate", validate)
    monkeypatch.setattr(
        manager.container_manager,
        "_inspect",
        lambda spec: ("verified", record.router_runtime_id, ""),
    )
    monkeypatch.setattr(
        manager.container_manager,
        "ensure_router",
        lambda spec: pytest.fail("existing registry path must not create/adopt the Router"),
    )

    before = Path(state.active_slot_map_path).read_bytes()
    result = manager.ensure_router(scope, _bindings())

    assert result.status == "ready"
    assert result.router_record == record
    assert observed["expected_active_slot"] == "slot_b"
    assert Path(state.active_slot_map_path).read_bytes() == before
    assert result.state_record == state


def test_existing_scope_missing_router_is_manual_reconciliation_not_recreation(tmp_path, monkeypatch):
    manager, history, _ = _manager(tmp_path)
    scope = _scope()
    record, state, network = _register_existing(
        tmp_path, history, scope, _bindings()
    )
    monkeypatch.setattr(
        manager.network_manager,
        "_inspect",
        lambda spec: ("verified", network, ""),
    )
    monkeypatch.setattr(
        manager,
        "_inspect_router_image_id",
        lambda runtime_id: ("verified", _image().image_id, ""),
    )
    monkeypatch.setattr(
        manager.image_manager,
        "inspect_image",
        lambda image_id: SimpleNamespace(status="verified", identity=_image(), detail=""),
    )
    monkeypatch.setattr(
        manager.image_manager,
        "build_and_verify",
        lambda: pytest.fail("existing Router reload must not rebuild its image"),
    )
    monkeypatch.setattr(
        manager.config_validator,
        "validate",
        lambda image_arg, state_arg, *, expected_active_slot=None: SimpleNamespace(status="valid", detail=""),
    )
    monkeypatch.setattr(
        manager.container_manager,
        "_inspect",
        lambda spec: ("missing", None, "No such container"),
    )
    monkeypatch.setattr(
        manager.container_manager,
        "ensure_router",
        lambda spec: pytest.fail("missing durable Router must not be recreated automatically"),
    )

    result = manager.ensure_router(scope, _bindings())
    assert result.status == "manual_reconciliation_required"
    assert "automatic recreation" in result.detail


def test_unregistered_existing_state_directory_is_never_overwritten(tmp_path, monkeypatch):
    manager, _, _ = _manager(tmp_path)
    scope = _scope()
    network = build_router_network_spec(scope)
    directory = manager.state_root / network.network_name
    directory.mkdir(parents=True, mode=0o700)
    marker = directory / "active-slot.map"
    marker.write_text("active slot_b\n", encoding="utf-8")
    before = marker.read_bytes()
    monkeypatch.setattr(
        manager.network_manager,
        "ensure_network",
        lambda requested: pytest.fail("orphan state must be rejected before network creation"),
    )

    result = manager.ensure_router(scope, _bindings())
    assert result.status == "manual_reconciliation_required"
    assert marker.read_bytes() == before
