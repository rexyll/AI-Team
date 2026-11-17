from __future__ import annotations

import os
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import runtime.local_docker_router_slot_manager as slot_module
from runtime.deployment_provider import DeploymentArtifact
from runtime.deployment_traffic_router import (
    TrafficPortBinding,
    TrafficRouteTarget,
    TrafficRouterScope,
)
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.local_docker_router_container import (
    RouterContainerVerification,
    build_router_container_spec,
)
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
from runtime.local_docker_router_state import LocalDockerRouterStateStore
from runtime.local_docker_routed_app import (
    DockerRoutedAppVerification,
    build_routed_app_container_spec,
)
from runtime.haproxy_runtime_readback import parse_show_servers_state


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Router slot mutation requires POSIX Host locking")


class FakeDockerRunner:
    def __init__(self):
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append(tuple(args))
        return DockerCommandResult(0, "{}", "")


def _state_row(
    backend: str,
    server: str,
    server_id: int,
    address: str,
    port: int,
    *,
    up: bool,
) -> str:
    return " ".join([
        "1",
        backend,
        str(server_id),
        server,
        address,
        "2" if up else "0",
        "0",
        "0",
        "0",
        "1",
        "6",
        "3" if up else "0",
        "2",
        "6" if up else "0",
        "0",
        "0",
        "0",
        "-",
        str(port),
        "-",
        "0",
        str(port),
        address,
        "-",
        "0",
    ])


def _state_response(backend: str, address: str, port: int, *, slot: str = "slot_b", up: bool = True) -> str:
    return _SERVER_HEADER + "\n" + _state_row(backend, slot, 2, address, port, up=up) + "\n"


def _full_state_response(bindings, address: str, active_slot: str = "slot_a") -> str:
    rows = []
    for backend_id, binding in enumerate(bindings, start=1):
        backend = f"be_p{binding.host_port}"
        for server_id, slot in enumerate(("slot_a", "slot_b"), start=1):
            selected = slot == active_slot
            rows.append(_state_row(
                backend,
                slot,
                server_id,
                address if selected else "127.0.0.1",
                binding.container_port if selected else 1,
                up=selected,
            ))
    return _SERVER_HEADER + "\n" + "\n".join(rows) + "\n"


_SERVER_HEADER = (
    "1\n"
    "# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state "
    "srv_uweight srv_iweight srv_time_since_last_change srv_check_status "
    "srv_check_result srv_check_health srv_check_state srv_agent_state "
    "bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl "
    "srv_check_port srv_check_addr srv_agent_addr srv_agent_port"
)


def _map_value(value: str) -> str:
    return (
        'type=beg, case=sensitive, found=yes, idx=tree, '
        'key="active", value="' + value + '", type="str"\n'
    )


class FakeRuntimeAPIClient:
    instances = []

    def __init__(self, provider, router_runtime_id):
        self.provider = provider
        self.router_runtime_id = router_runtime_id
        self.commands = []
        self.writes = []
        self.active_selector = "none"
        self.final_selector_override = None
        self.fail_first_write = False
        self.stat_status = "UP"
        self.state_address_override = None
        self._get_count = 0
        self._write_failed = False
        self.__class__.instances.append(self)

    def execute(self, command):
        line = command.line
        self.commands.append(line)
        if command.operation == "show_maps":
            return SimpleNamespace(
                status="succeeded",
                operation=command.operation,
                response="0 (/usr/local/etc/haproxy/active-slot.map) active map\n",
                detail="",
            )
        if command.operation == "get_map":
            self._get_count += 1
            value = self.active_selector
            if self.final_selector_override is not None and self._get_count > 1:
                value = self.final_selector_override
            return SimpleNamespace(
                status="succeeded",
                operation=command.operation,
                response=_map_value(value),
                detail="",
            )
        if command.operation in {"set_server_address", "set_server_state"}:
            self.writes.append(line)
            if self.fail_first_write and not self._write_failed:
                self._write_failed = True
                return SimpleNamespace(
                    status="failed",
                    operation=command.operation,
                    response="",
                    detail="injected one-shot Runtime API write failure",
                )
            return SimpleNamespace(
                status="succeeded",
                operation=command.operation,
                response="",
                detail="",
            )
        if command.operation == "show_servers_state":
            if line == "show servers state":
                response = _full_state_response(
                    BINDINGS,
                    self.state_address_override or TARGET_ADDRESS,
                    active_slot="slot_b",
                )
            else:
                backend = line.split()[-1]
                binding = next(x for x in BINDINGS if f"be_p{x.host_port}" == backend)
                response = _state_response(
                    backend,
                    self.state_address_override or TARGET_ADDRESS,
                    binding.container_port,
                    slot="slot_b",
                    up=True,
                )
            return SimpleNamespace(
                status="succeeded",
                operation=command.operation,
                response=response,
                detail="",
            )
        if command.operation == "show_stat_servers":
            backend = line.split()[2]
            response = (
                "# pxname,svname,scur,status\n"
                f"{backend},slot_b,2,{self.stat_status}\n"
            )
            return SimpleNamespace(
                status="succeeded",
                operation=command.operation,
                response=response,
                detail="",
            )
        raise AssertionError(f"unexpected Runtime API operation: {command.operation} ({line})")


TARGET_ADDRESS = "172.18.0.2"
ROUTER_ID = "r" * 64
APP_ID = "c" * 64
BINDINGS = (TrafficPortBinding(8080, 80), TrafficPortBinding(8443, 443))


def _fixture(tmp_path):
    scope = TrafficRouterScope("docker-local", "slot-manager", "test")
    network_spec = build_router_network_spec(scope)
    network = DockerRouterNetworkRecord(
        network_spec.network_name,
        "b" * 64,
        network_spec.scope_fingerprint,
        "bridge",
        False,
        False,
    )
    image = DockerRouterImageIdentity(
        "sha256:" + "a" * 64,
        "linux",
        "amd64",
        ROUTER_HAPROXY_VERSION,
        ROUTER_SOCAT_PACKAGE_VERSION,
        ROUTER_BASE_IMAGE_REF,
        "1",
    )
    state_store = LocalDockerRouterStateStore(tmp_path / "host-state")
    persisted = state_store.persist(scope, BINDINGS, active_slot=None)
    assert persisted.status == "persisted" and persisted.record is not None
    router_spec = build_router_container_spec(
        scope, BINDINGS, network, image, persisted.record
    )
    artifact = DeploymentArtifact("docker-local", "app:test", "d" * 64, "v1")
    app_spec = build_routed_app_container_spec(
        network, artifact, "deploy-slot-manager", BINDINGS
    )
    target = TrafficRouteTarget(
        "deploy-slot-manager",
        APP_ID,
        TARGET_ADDRESS,
        BINDINGS,
    )
    return scope, network, image, persisted.record, router_spec, app_spec, target


def _patched_verifiers(monkeypatch, target, *, healthy=True, target_after=None):
    router_calls = []

    def verify_router(payload, spec):
        router_calls.append(payload)
        return RouterContainerVerification("verified", ROUTER_ID)

    app_calls = []

    def verify_app(payload, spec):
        app_calls.append(payload)
        current_target = target if len(app_calls) == 1 or target_after is None else target_after
        return DockerRoutedAppVerification(
            "verified",
            current_target,
            "healthy" if healthy else "unknown",
            "" if healthy else "app health is not fresh and healthy",
        )

    monkeypatch.setattr(slot_module, "verify_router_container_inspection", verify_router)
    monkeypatch.setattr(slot_module, "verify_routed_app_inspection", verify_app)


def _manager(monkeypatch, *, runtime_client=None, runner=None, attempts=1):
    client_type = runtime_client or FakeRuntimeAPIClient
    client_type.instances = []
    monkeypatch.setattr(slot_module, "HAProxyRuntimeAPIClient", client_type)
    monkeypatch.setattr(slot_module, "_scope_operation_lock", lambda record: nullcontext())
    provider = LocalDockerProvider(runner or FakeDockerRunner())
    return slot_module.LocalDockerRouterSlotManager(
        provider,
        readback_attempts=attempts,
        readback_interval_seconds=0.05,
    ), client_type


def test_prepare_inactive_slot_writes_once_reads_back_and_persists_server_state(tmp_path, monkeypatch):
    _, network, _, state, router_spec, app_spec, target = _fixture(tmp_path)
    _patched_verifiers(monkeypatch, target)
    manager, client_type = _manager(monkeypatch)
    result = manager.prepare_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=router_spec,
        network=network,
        app_spec=app_spec,
        target=target,
        slot="slot_b",
        state_record=state,
    )
    assert result.status == "verified"
    assert result.active_selector_before == "none"
    assert result.active_selector_after == "none"
    assert result.target == target
    assert len(result.observations) == 2
    assert {item.current_sessions for item in result.observations} == {2}
    assert result.state_record is not None
    assert result.state_record.server_state_sha256 != state.server_state_sha256
    assert result.state_record.server_state_sha256 == __import__("hashlib").sha256(
        Path(result.state_record.server_state_path).read_bytes()
    ).hexdigest()
    client = client_type.instances[-1]
    assert len(client.writes) == 4
    assert sum(line.startswith("set server ") for line in client.writes) == 4
    assert not any(line.startswith("set map ") for line in client.commands)
    assert not any(line.startswith("set map ") for line in client.writes)


def test_prepare_refuses_to_write_the_currently_active_slot(tmp_path, monkeypatch):
    _, network, _, state, router_spec, app_spec, target = _fixture(tmp_path)
    _patched_verifiers(monkeypatch, target)
    manager, client_type = _manager(monkeypatch)

    class ActiveRuntimeClient(FakeRuntimeAPIClient):
        def __init__(self, provider, router_runtime_id):
            super().__init__(provider, router_runtime_id)
            self.active_selector = "slot_b"

    manager, client_type = _manager(monkeypatch, runtime_client=ActiveRuntimeClient)
    result = manager.prepare_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=router_spec,
        network=network,
        app_spec=app_spec,
        target=target,
        slot="slot_b",
        state_record=state,
    )
    assert result.status == "mismatch"
    assert client_type.instances[-1].writes == []


def test_prepare_refuses_unhealthy_app_before_any_runtime_api_write(tmp_path, monkeypatch):
    _, network, _, state, router_spec, app_spec, target = _fixture(tmp_path)
    _patched_verifiers(monkeypatch, target, healthy=False)
    manager, client_type = _manager(monkeypatch)
    result = manager.prepare_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=router_spec,
        network=network,
        app_spec=app_spec,
        target=target,
        slot="slot_b",
        state_record=state,
    )
    assert result.status == "mismatch"
    assert client_type.instances == []


def test_prepare_does_not_retry_runtime_api_write_on_failure(tmp_path, monkeypatch):
    _, network, _, state, router_spec, app_spec, target = _fixture(tmp_path)
    _patched_verifiers(monkeypatch, target)
    manager, client_type = _manager(monkeypatch)

    class FailedWriteClient(FakeRuntimeAPIClient):
        def __init__(self, provider, router_runtime_id):
            super().__init__(provider, router_runtime_id)
            self.fail_first_write = True
            self.state_address_override = "127.0.0.1"

    manager, client_type = _manager(monkeypatch, runtime_client=FailedWriteClient)
    result = manager.prepare_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=router_spec,
        network=network,
        app_spec=app_spec,
        target=target,
        slot="slot_b",
        state_record=state,
    )
    assert result.status == "mismatch"
    writes = client_type.instances[-1].writes
    assert len(writes) == 1
    assert writes[0].startswith("set server be_p8080/slot_b addr ")


def test_prepare_fails_when_backend_readback_is_not_up(tmp_path, monkeypatch):
    _, network, _, state, router_spec, app_spec, target = _fixture(tmp_path)
    _patched_verifiers(monkeypatch, target)
    manager, client_type = _manager(monkeypatch, attempts=2)

    class DownRuntimeClient(FakeRuntimeAPIClient):
        def __init__(self, provider, router_runtime_id):
            super().__init__(provider, router_runtime_id)
            self.stat_status = "DOWN"

    manager, client_type = _manager(
        monkeypatch, runtime_client=DownRuntimeClient, attempts=2
    )
    result = manager.prepare_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=router_spec,
        network=network,
        app_spec=app_spec,
        target=target,
        slot="slot_b",
        state_record=state,
    )
    assert result.status == "mismatch"
    assert len(client_type.instances[-1].writes) == 4
    assert not any(line.startswith("set map ") for line in client_type.instances[-1].commands)


def test_prepare_fails_if_active_selector_changes_during_operation(tmp_path, monkeypatch):
    _, network, _, state, router_spec, app_spec, target = _fixture(tmp_path)
    _patched_verifiers(monkeypatch, target)
    manager, client_type = _manager(monkeypatch)

    class SelectorRaceClient(FakeRuntimeAPIClient):
        def __init__(self, provider, router_runtime_id):
            super().__init__(provider, router_runtime_id)
            self.final_selector_override = "slot_a"

    manager, client_type = _manager(monkeypatch, runtime_client=SelectorRaceClient)
    result = manager.prepare_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=router_spec,
        network=network,
        app_spec=app_spec,
        target=target,
        slot="slot_b",
        state_record=state,
    )
    assert result.status == "mismatch"
    assert result.active_selector_before == "none"
    assert result.active_selector_after is None
    assert not any(line.startswith("set map ") for line in client_type.instances[-1].commands)


def test_prepare_rejects_cross_scope_app_or_router_before_docker_io(tmp_path, monkeypatch):
    _, network, _, state, router_spec, app_spec, target = _fixture(tmp_path)
    runner = FakeDockerRunner()
    manager, client_type = _manager(monkeypatch, runner=runner)
    other_app = app_spec.__class__(
        **{
            **app_spec.__dict__,
            "network_id": "e" * 64,
        }
    )
    result = manager.prepare_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=router_spec,
        network=network,
        app_spec=other_app,
        target=target,
        slot="slot_b",
        state_record=state,
    )
    assert result.status == "mismatch"
    assert runner.calls == []
    assert client_type.instances == []
