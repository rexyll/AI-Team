from __future__ import annotations

import pytest

from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.haproxy_runtime_api import (
    HAProxyRuntimeAPIClient,
    HAProxyRuntimeCommand,
    get_map_command,
    set_map_command,
    set_server_address_command,
    set_server_state_command,
    show_info_command,
    show_maps_command,
    show_servers_connections_command,
    show_servers_state_command,
    show_stat_command,
)


class InputRunner:
    def __init__(self, result=None):
        self.result = result or DockerCommandResult(0, "response", "")
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        raise AssertionError("stdin operation must call execute_input")

    def execute_input(self, args, *, input_text, cwd, timeout):
        self.calls.append((list(args), input_text, cwd, timeout))
        return self.result


def _provider(runner):
    return LocalDockerProvider(runner)


def test_read_commands_are_allowlisted_and_have_expected_text():
    assert show_info_command().line == "show info"
    assert show_maps_command().line == "show map"
    assert show_stat_command().line == "show stat"
    assert show_servers_state_command().line == "show servers state"
    assert show_servers_connections_command().line == "show servers conn"
    assert show_servers_connections_command("be_p8080").line == "show servers conn be_p8080"
    assert get_map_command("/usr/local/etc/haproxy/active-slot.map", "active").line == (
        "get map /usr/local/etc/haproxy/active-slot.map active"
    )


def test_mutating_commands_validate_every_component():
    assert set_map_command("/usr/local/etc/haproxy/active-slot.map", "active", "slot_b").line == (
        "set map /usr/local/etc/haproxy/active-slot.map active slot_b"
    )
    assert set_server_address_command("be_p8080", "slot_a", "172.20.0.4", 80).line == (
        "set server be_p8080/slot_a addr 172.20.0.4 port 80"
    )
    assert set_server_state_command("be_p8080", "slot_a", "drain").line == (
        "set server be_p8080/slot_a state drain"
    )


@pytest.mark.parametrize("bad", ["be p8080", "be_p8080;shutdown sessions", "x\nshutdown", "../be", ""])
def test_backend_and_server_names_reject_command_injection(bad):
    with pytest.raises(ValueError):
        set_server_state_command(bad, "slot_a", "ready")


@pytest.mark.parametrize("bad", ["/tmp/x\nshutdown", "/tmp/../admin.map", "", "relative.map"])
def test_map_paths_reject_traversal_and_newlines(bad):
    with pytest.raises(ValueError):
        get_map_command(bad, "active")


def test_runtime_api_accepts_only_numeric_map_ids_or_safe_paths():
    assert get_map_command("#0", "active").line == "get map #0 active"
    assert set_map_command("#0", "active", "none").line == "set map #0 active none"
    for bad in ("#x", "#-1", "#1000000", "#0;shutdown"):
        with pytest.raises(ValueError):
            get_map_command(bad, "active")


def test_map_values_are_limited_to_known_router_slots():
    with pytest.raises(ValueError, match="map value"):
        set_map_command("/usr/local/etc/haproxy/active-slot.map", "active", "old;shutdown")


def test_server_address_and_port_are_literal_and_bounded():
    with pytest.raises(ValueError, match="literal IP"):
        set_server_address_command("be_p8080", "slot_a", "candidate.local", 80)
    with pytest.raises(ValueError, match="1..65535"):
        set_server_address_command("be_p8080", "slot_a", "172.20.0.4", True)
    with pytest.raises(ValueError, match="1..65535"):
        set_server_address_command("be_p8080", "slot_a", "172.20.0.4", 65536)


def test_command_dataclass_cannot_bypass_the_allowlist():
    with pytest.raises(ValueError, match="allowlisted operation"):
        HAProxyRuntimeCommand("shutdown sessions", "show_info", False)
    with pytest.raises(ValueError, match="mutability flag"):
        HAProxyRuntimeCommand("set map /tmp/map active slot_a", "set_map", False)


@pytest.mark.parametrize("line,operation", [
    ("get map /tmp/../admin.map active", "get_map"),
    ("set map /tmp/../admin.map active slot_a", "set_map"),
    ("set server be_p8080/slot_a addr 999.1.1.1 port 80", "set_server_address"),
    ("set server be_p8080/slot_a addr 172.20.0.4 port 99999", "set_server_address"),
])
def test_direct_command_construction_cannot_bypass_factory_validation(line, operation):
    with pytest.raises(ValueError):
        HAProxyRuntimeCommand(line, operation, operation != "get_map")


def test_client_targets_full_immutable_router_id_and_uses_stdin():
    runner = InputRunner(DockerCommandResult(0, "Name: HAProxy\n", ""))
    client = HAProxyRuntimeAPIClient(_provider(runner), "a" * 64)
    result = client.execute(show_info_command())
    assert result.status == "succeeded"
    assert runner.calls == [(
        ["exec", "-i", "a" * 64, "socat", "-T", "5", "STDIO",
         "UNIX-CONNECT:/run/haproxy/admin.sock"],
        "show info\n", None, 7.0,
    )]


def test_client_rejects_mutable_router_name_and_custom_admin_socket():
    runner = InputRunner()
    with pytest.raises(ValueError, match="immutable Docker"):
        HAProxyRuntimeAPIClient(_provider(runner), "router-name")
    with pytest.raises(ValueError, match="fixed"):
        HAProxyRuntimeAPIClient(
            _provider(runner), "a" * 64, admin_socket="/tmp/other.sock"
        )
    assert runner.calls == []


def test_client_reports_runner_without_stdin_as_unavailable():
    class Runner:
        def __init__(self):
            self.calls = []
        def execute(self, args, *, cwd, timeout):
            self.calls.append(list(args))
            return DockerCommandResult(0, "", "")
    runner = Runner()
    result = HAProxyRuntimeAPIClient(_provider(runner), "a" * 64).execute(show_stat_command())
    assert result.status == "unavailable"
    assert "does not support stdin" in result.detail
    assert runner.calls == []


def test_client_preserves_docker_and_runtime_api_failures():
    runner = InputRunner(DockerCommandResult(1, "", "permission denied"))
    result = HAProxyRuntimeAPIClient(_provider(runner), "a" * 64).execute(
        set_map_command("/usr/local/etc/haproxy/active-slot.map", "active", "slot_a")
    )
    assert result.status == "failed"
    assert "permission denied" in result.detail
