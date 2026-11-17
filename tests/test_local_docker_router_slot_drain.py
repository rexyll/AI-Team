from __future__ import annotations

from types import SimpleNamespace

import pytest

import runtime.local_docker_router_slot_manager as slot_module
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
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
from runtime.local_docker_router_container import build_router_container_spec
from runtime.local_docker_router_slot_manager import LocalDockerRouterSlotManager
from runtime.local_docker_router_state import LocalDockerRouterStateStore


ROUTER_ID = "a" * 64
BINDINGS = (TrafficPortBinding(42699, 18080),)


def _servers_state():
    header = (
        "# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state "
        "srv_uweight srv_iweight srv_time_since_last_change srv_check_status "
        "srv_check_result srv_check_health srv_check_state srv_agent_state "
        "bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl "
        "srv_check_port srv_check_addr srv_agent_addr srv_agent_port"
    )
    rows = [
        "1 be_p42699 1 slot_a 127.0.0.1 0 0 0 0 0 6 0 0 6 0 0 0 - 18080 - 0 18080 127.0.0.1 - 0",
        "1 be_p42699 2 slot_b 127.0.0.1 0 0 0 0 0 6 0 0 6 0 0 0 - 18080 - 0 18080 127.0.0.1 - 0",
    ]
    return "1\n" + header + "\n" + "\n".join(rows) + "\n"


class RuntimeRunner:
    def __init__(self, *, sessions=0, fail_drain=False):
        self.sessions = sessions
        self.fail_drain = fail_drain
        self.commands = []

    def execute(self, args, *, cwd, timeout):
        raise AssertionError("Docker inspect is replaced by the exact identity fixture")

    def execute_input(self, args, *, input_text, cwd, timeout):
        command = input_text.strip()
        self.commands.append(command)
        if command.startswith("show map"):
            output = "0 (/etc/haproxy/active-slot.map) type=map\n"
        elif command.startswith("get map"):
            output = "type=ip,type=string,found=yes,key=active,value=slot_a\n"
        elif command.startswith("set server") and command.endswith(" state drain") and self.fail_drain:
            return DockerCommandResult(1, "", "injected drain failure"), None
        elif command.startswith("show stat"):
            state = "DRAIN" if any(x.endswith(" state drain") for x in self.commands) else "UP"
            if any(x.endswith(" state maint") for x in self.commands):
                state = "MAINT"
            output = f"# pxname,svname,status,scur\nbe_p42699,slot_b,{state},{self.sessions}\n"
        elif command.startswith("set server") and command.endswith(" state drain"):
            output = ""
        elif command.startswith("set server") and command.endswith(" state maint"):
            output = ""
        elif command == "show servers state":
            output = _servers_state()
        else:
            return DockerCommandResult(1, "", "unexpected Runtime API command"), None
        return DockerCommandResult(0, output, ""), None


def _fixture(tmp_path, monkeypatch, *, sessions=0, fail_drain=False):
    scope = TrafficRouterScope("docker-local", "drain-test", "staging")
    network_spec = build_router_network_spec(scope)
    network = DockerRouterNetworkRecord(
        network_spec.network_name, "b" * 64, network_spec.scope_fingerprint,
        "bridge", False, False,
    )
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    initial = store.persist(scope, BINDINGS)
    assert initial.status == "persisted"
    servers = store.persist_servers_state(initial.record, BINDINGS, _servers_state())
    assert servers.status == "persisted"
    active = store.persist_active_slot_map(
        servers.record, expected_active_slot=None, active_slot="slot_a"
    )
    assert active.status == "persisted"
    image = DockerRouterImageIdentity(
        "sha256:" + "c" * 64, "linux", "amd64",
        ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION,
        ROUTER_BASE_IMAGE_REF, "1",
    )
    spec = build_router_container_spec(
        scope, BINDINGS, network, image, active.record,
        expected_active_slot="slot_a",
    )
    runner = RuntimeRunner(sessions=sessions, fail_drain=fail_drain)
    provider = LocalDockerProvider(runner)
    manager = LocalDockerRouterSlotManager(
        provider, readback_attempts=1, readback_interval_seconds=0.05
    )
    monkeypatch.setattr(
        manager, "_inspect_payload",
        lambda argv: ("verified", {"Id": ROUTER_ID}, ""),
    )
    monkeypatch.setattr(
        slot_module, "verify_router_container_inspection",
        lambda payload, requested: SimpleNamespace(
            status="verified", container_id=ROUTER_ID, detail=""
        ),
    )
    return manager, provider, network, spec, active.record, runner


def test_drain_inactive_slot_waits_for_zero_sessions_then_confirms_maint(tmp_path, monkeypatch):
    manager, _, network, spec, state, runner = _fixture(tmp_path, monkeypatch)

    result = manager.drain_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=spec,
        network=network,
        slot="slot_b",
        expected_active_slot="slot_a",
        state_record=state,
    )

    assert result.status == "verified"
    assert result.active_selector == "slot_a"
    assert result.remaining_connections == 0
    assert result.state_record is not None
    assert runner.commands.count("set server be_p42699/slot_b state drain") == 1
    assert runner.commands.count("set server be_p42699/slot_b state maint") == 1
    assert runner.commands[-1] == "show servers state"


def test_drain_timeout_keeps_slot_unretired_and_reports_remaining_sessions(tmp_path, monkeypatch):
    manager, _, network, spec, state, runner = _fixture(
        tmp_path, monkeypatch, sessions=3
    )

    result = manager.drain_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=spec,
        network=network,
        slot="slot_b",
        expected_active_slot="slot_a",
        state_record=state,
    )

    assert result.status == "indeterminate"
    assert result.remaining_connections == 3
    assert result.state_record is None
    assert not any(command.endswith(" state maint") for command in runner.commands)


def test_drain_ambiguous_write_is_not_retried_or_followed_by_maintenance(tmp_path, monkeypatch):
    manager, _, network, spec, state, runner = _fixture(
        tmp_path, monkeypatch, fail_drain=True
    )

    result = manager.drain_inactive_slot(
        router_runtime_id=ROUTER_ID,
        router_spec=spec,
        network=network,
        slot="slot_b",
        expected_active_slot="slot_a",
        state_record=state,
    )

    assert result.status == "indeterminate"
    assert runner.commands.count("set server be_p42699/slot_b state drain") == 1
    assert not any(command.endswith(" state maint") for command in runner.commands)


def test_active_slot_cannot_be_drained(tmp_path, monkeypatch):
    manager, _, network, spec, state, _ = _fixture(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="must differ"):
        manager.drain_inactive_slot(
            router_runtime_id=ROUTER_ID,
            router_spec=spec,
            network=network,
            slot="slot_a",
            expected_active_slot="slot_a",
            state_record=state,
        )
