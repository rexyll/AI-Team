"""Allowlisted HAProxy Runtime API commands and Host-only Docker socket client.

No arbitrary CLI text, shell fragments, mutable container names or arbitrary
Docker exec commands are accepted by this module.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal

from runtime.local_docker_provider import LocalDockerProvider

RouterCommandStatus = Literal["succeeded", "failed", "unavailable"]
ServerRuntimeState = Literal["ready", "drain", "maint"]

_RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_MAP_PATH = re.compile(r"^/[a-zA-Z0-9_./-]{1,180}$")
_MAX_COMMAND_BYTES = 1023
_DEFAULT_ADMIN_SOCKET = "/run/haproxy/admin.sock"


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a safe lowercase Router identifier")
    return value


def _map_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _MAP_PATH.fullmatch(value)
        or "/../" in value
        or value.endswith("/..")
    ):
        raise ValueError("map_path must be a safe absolute Router map path")
    return value


def _line(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(ch in value for ch in ("\x00", "\r", "\n"))
        or len(value.encode("utf-8")) > _MAX_COMMAND_BYTES
    ):
        raise ValueError("Runtime API command must be one bounded line without NUL")
    return value


@dataclass(frozen=True)
class HAProxyRuntimeCommand:
    line: str
    operation: Literal[
        "show_info", "show_stat", "show_servers_state", "show_servers_conn",
        "get_map", "set_map", "set_server_address", "set_server_state",
    ]
    mutating: bool

    def __post_init__(self) -> None:
        _line(self.line)
        patterns = {
            "show_info": r"show info",
            "show_stat": r"show stat",
            "show_servers_state": r"show servers state",
            "show_servers_conn": r"show servers conn(?: [a-z][a-z0-9_-]{0,47})?",
            "get_map": r"get map /[a-zA-Z0-9_./-]{1,180} [a-z][a-z0-9_-]{0,47}",
            "set_map": r"set map /[a-zA-Z0-9_./-]{1,180} [a-z][a-z0-9_-]{0,47} (?:none|slot_a|slot_b)",
            "set_server_address": (
                r"set server [a-z][a-z0-9_-]{0,47}/[a-z][a-z0-9_-]{0,47} "
                r"addr [0-9a-fA-F:.]+ port [0-9]{1,5}"
            ),
            "set_server_state": (
                r"set server [a-z][a-z0-9_-]{0,47}/[a-z][a-z0-9_-]{0,47} "
                r"state (?:ready|drain|maint)"
            ),
        }
        if self.operation not in patterns or not re.fullmatch(patterns[self.operation], self.line):
            raise ValueError("Runtime API command text does not match its allowlisted operation")
        expected_mutating = self.operation in {
            "set_map", "set_server_address", "set_server_state",
        }
        if not isinstance(self.mutating, bool) or self.mutating != expected_mutating:
            raise ValueError("command mutability flag does not match its operation")


@dataclass(frozen=True)
class HAProxyRuntimeCommandResult:
    status: RouterCommandStatus
    operation: str
    response: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "unavailable"}:
            raise ValueError("invalid HAProxy Runtime API result status")
        if not isinstance(self.operation, str) or not self.operation:
            raise ValueError("operation must be non-empty")
        if not isinstance(self.response, str) or not isinstance(self.detail, str):
            raise TypeError("response and detail must be strings")


def show_info_command() -> HAProxyRuntimeCommand:
    return HAProxyRuntimeCommand("show info", "show_info", False)


def show_stat_command() -> HAProxyRuntimeCommand:
    return HAProxyRuntimeCommand("show stat", "show_stat", False)


def show_servers_state_command() -> HAProxyRuntimeCommand:
    return HAProxyRuntimeCommand("show servers state", "show_servers_state", False)


def show_servers_connections_command(backend: str | None = None) -> HAProxyRuntimeCommand:
    line = "show servers conn"
    if backend is not None:
        line += " " + _identifier(backend, "backend")
    return HAProxyRuntimeCommand(line, "show_servers_conn", False)


def get_map_command(map_path: str, key: str) -> HAProxyRuntimeCommand:
    return HAProxyRuntimeCommand(
        f"get map {_map_path(map_path)} {_identifier(key, 'map key')}",
        "get_map", False,
    )


def set_map_command(map_path: str, key: str, value: str) -> HAProxyRuntimeCommand:
    if value not in {"none", "slot_a", "slot_b"}:
        raise ValueError("map value must be none, slot_a, or slot_b")
    return HAProxyRuntimeCommand(
        f"set map {_map_path(map_path)} {_identifier(key, 'map key')} {value}",
        "set_map", True,
    )


def set_server_address_command(
    backend: str, server: str, address: str, port: int
) -> HAProxyRuntimeCommand:
    safe_backend = _identifier(backend, "backend")
    safe_server = _identifier(server, "server")
    try:
        safe_address = str(ipaddress.ip_address(address))
    except (TypeError, ValueError) as exc:
        raise ValueError("server address must be a literal IP address") from exc
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("server port must be an integer in the range 1..65535")
    return HAProxyRuntimeCommand(
        f"set server {safe_backend}/{safe_server} addr {safe_address} port {port}",
        "set_server_address", True,
    )


def set_server_state_command(
    backend: str, server: str, state: ServerRuntimeState
) -> HAProxyRuntimeCommand:
    if state not in {"ready", "drain", "maint"}:
        raise ValueError("server state must be ready, drain, or maint")
    return HAProxyRuntimeCommand(
        f"set server {_identifier(backend, 'backend')}/{_identifier(server, 'server')} state {state}",
        "set_server_state", True,
    )


class HAProxyRuntimeAPIClient:
    """Send one allowlisted Runtime API command to a Router Unix socket."""

    def __init__(
        self,
        provider: LocalDockerProvider,
        router_runtime_id: str,
        *,
        admin_socket: str = _DEFAULT_ADMIN_SOCKET,
        timeout: float = 5.0,
    ) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        if not isinstance(router_runtime_id, str) or not _RUNTIME_ID.fullmatch(router_runtime_id):
            raise ValueError("router_runtime_id must be a full immutable Docker container ID")
        if admin_socket != _DEFAULT_ADMIN_SOCKET:
            raise ValueError("admin socket path is fixed by the Router security contract")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 15:
            raise ValueError("timeout must be in the range (0, 15]")
        self.provider = provider
        self.router_runtime_id = router_runtime_id
        self.admin_socket = admin_socket
        self.timeout = float(timeout)

    def execute(self, command: HAProxyRuntimeCommand) -> HAProxyRuntimeCommandResult:
        if not isinstance(command, HAProxyRuntimeCommand):
            raise TypeError("command must be an allowlisted HAProxyRuntimeCommand")
        args = [
            "exec", "-i", self.router_runtime_id, "socat", "-T",
            f"{self.timeout:g}", "STDIO", f"UNIX-CONNECT:{self.admin_socket}",
        ]
        result, error = self.provider.execute_host_input(
            args, input_text=command.line + "\n", timeout=self.timeout + 2.0
        )
        if error:
            return HAProxyRuntimeCommandResult("unavailable", command.operation, detail=error)
        assert result is not None
        if result.returncode != 0:
            return HAProxyRuntimeCommandResult(
                "failed", command.operation,
                response=result.stdout[-4000:],
                detail=(result.stderr or "Docker exec / HAProxy Runtime API command failed")[-1000:],
            )
        return HAProxyRuntimeCommandResult(
            "succeeded", command.operation,
            response=result.stdout[-4000:],
            detail=result.stderr[-1000:] if result.stderr else "",
        )
