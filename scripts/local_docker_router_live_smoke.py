"""Ephemeral Docker Engine smoke for a real HAProxy Router bootstrap.

This is an integration probe, not a production deployment command. It creates
one unique scope, starts the pinned Router with the fail-closed none map,
reads its Runtime API through the Host-only immutable-ID transport, then
removes only resources whose immutable IDs were verified as created here.
It never creates an application container or switches traffic.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.haproxy_runtime_api import (
    HAProxyRuntimeAPIClient,
    get_map_command,
    show_maps_command,
    show_info_command,
)
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_config import HAPROXY_ACTIVE_SLOT_MAP
from runtime.local_docker_router_config_validator import LocalDockerRouterConfigValidator
from runtime.local_docker_router_container import build_router_container_spec
from runtime.local_docker_router_container_manager import LocalDockerRouterContainerManager
from runtime.local_docker_router_image import LocalDockerRouterImageManager
from runtime.local_docker_router_network import LocalDockerRouterNetworkManager
from runtime.local_docker_router_state import LocalDockerRouterStateStore

_EXPECTED_HAPROXY_VERSION = "3.4.7"
_RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")


def parse_show_info(response: str) -> dict[str, str]:
    """Parse HAProxy show-info output and require the pinned runtime version."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("HAProxy show info returned an empty response")
    fields: dict[str, str] = {}
    for line in response.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if not key or key in fields:
            raise ValueError("HAProxy show info contains an empty or duplicate field")
        fields[key] = value
    if fields.get("Name") != "HAProxy":
        raise ValueError("Runtime API did not identify the expected HAProxy process")
    version = fields.get("Version", "")
    match = re.match(r"^(\d+\.\d+\.\d+)(?:[-+~.]|$)", version)
    if match is None or match.group(1) != _EXPECTED_HAPROXY_VERSION:
        raise ValueError("Runtime API version does not match the pinned HAProxy release")
    return fields


def parse_show_map_registry(response: str, *, expected_path: str) -> str:
    """Resolve one exact HAProxy map file registration to its numeric ID."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("HAProxy show map returned an empty registry")
    matches: list[str] = []
    for line in response.splitlines():
        match = re.match(r"^\\s*([0-9]{1,6})\\s+\\((/[^)]+)\\)(?:\\s|$)", line)
        if match is None:
            continue
        if match.group(2) == expected_path:
            matches.append(f"#{match.group(1)}")
    if len(matches) != 1:
        raise ValueError("HAProxy show map did not return exactly one registration for the expected file")
    return matches[0]


def parse_get_map_value(
    response: str, *, expected_key: str, expected_value: str
) -> str:
    """Parse the structured get-map response; reject missing/ambiguous fields."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("HAProxy get map returned an empty response")
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("HAProxy get map must return exactly one result line")
    fields: dict[str, str] = {}
    type_field_count = 0
    for item in lines[0].split(","):
        key, separator, raw_value = item.partition("=")
        key = key.strip()
        raw_value = raw_value.strip()
        if not separator or not key or not raw_value:
            raise ValueError("HAProxy get map returned malformed fields")
        if raw_value.startswith('"'):
            if len(raw_value) < 2 or not raw_value.endswith('"'):
                raise ValueError("HAProxy get map returned an unterminated quoted field")
            value = raw_value[1:-1]
        else:
            value = raw_value
        # HAProxy returns both the map match type and the stored value type
        # under the field name "type". Other fields must remain unique.
        if key == "type":
            type_field_count += 1
            if type_field_count > 2:
                raise ValueError("HAProxy get map returned too many type fields")
            continue
        if key in fields:
            raise ValueError("HAProxy get map returned duplicate selector fields")
        fields[key] = value
    if type_field_count not in {1, 2}:
        raise ValueError("HAProxy get map omitted the map type metadata")
    if fields.get("found") != "yes" or fields.get("key") != expected_key:
        raise ValueError("HAProxy get map did not confirm the requested key")
    value = fields.get("value")
    if not value:
        raise ValueError("HAProxy get map omitted the selector value")
    if value != expected_value:
        raise ValueError("HAProxy get map returned an unexpected selector value")
    return value


def wait_for_runtime_api_show_info(
    client: HAProxyRuntimeAPIClient,
    *,
    attempts: int = 40,
    interval_seconds: float = 0.25,
):
    """Wait briefly for HAProxy's admin socket after container start.

    Only transient missing/not-yet-listening Unix-socket errors are retried.
    This is a read-only readiness probe; no Runtime API write is retried.
    """
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 80:
        raise ValueError("attempts must be an integer in the range 1..80")
    if (
        not isinstance(interval_seconds, (int, float))
        or isinstance(interval_seconds, bool)
        or not 0 < interval_seconds <= 1
    ):
        raise ValueError("interval_seconds must be in the range (0, 1]")
    retryable_markers = (
        "no such file or directory",
        "connection refused",
        "container is restarting",
        "oci runtime exec failed",
    )
    result = None
    for attempt in range(attempts):
        result = client.execute(show_info_command())
        if result.status == "succeeded":
            return result
        detail = (result.detail or "").lower()
        if result.status != "failed" or not any(
            marker in detail for marker in retryable_markers
        ):
            return result
        if attempt + 1 < attempts:
            time.sleep(interval_seconds)
    return result


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("0.0.0.0", 0))
        return int(listener.getsockname()[1])


def _run_docker(provider: LocalDockerProvider, arguments: list[str]) -> str:
    result, error = provider._execute(arguments)
    if error:
        raise RuntimeError(f"Docker cleanup command could not run: {type(error).__name__}")
    assert result is not None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Docker cleanup command failed").strip()
        raise RuntimeError(detail[:500])
    return result.stdout


_CLEANUP_CONTAINER_INSPECT_FORMAT = (
    r'{{printf "{\"Id\":%q,\"Config\":{\"Labels\":%s},\"State\":{\"Running\":%t}}" .Id (json .Config.Labels) .State.Running}}'
)
_CLEANUP_NETWORK_INSPECT_FORMAT = (
    r'{{printf "{\"Id\":%q,\"Labels\":%s}" .Id (json .Labels)}}'
)


def _inspect_json(provider: LocalDockerProvider, arguments: list[str]) -> dict[str, Any]:
    raw = _run_docker(provider, arguments)
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Docker cleanup inspect returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Docker cleanup inspect did not return one object")
    return value


def _cleanup_owned_resources(
    provider: LocalDockerProvider,
    *,
    router_id: str | None,
    router_owned: bool,
    network_id: str | None,
    network_owned: bool,
    scope_fingerprint: str | None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "status": "not_required",
        "router_removed": False,
        "network_removed": False,
        "detail": "",
    }
    try:
        if router_id is not None and router_owned:
            if not _RUNTIME_ID.fullmatch(router_id):
                raise RuntimeError("refusing cleanup without a full immutable Router ID")
            current = _inspect_json(
                provider, ["container", "inspect", "--format", _CLEANUP_CONTAINER_INSPECT_FORMAT, router_id]
            )
            labels = (current.get("Config") or {}).get("Labels")
            if (
                current.get("Id") != router_id
                or not isinstance(labels, dict)
                or labels.get("com.ai-team.router.managed") != "true"
                or labels.get("com.ai-team.router.scope-sha256") != scope_fingerprint
            ):
                raise RuntimeError("Router immutable identity/scope changed; cleanup refused")
            state = current.get("State")
            if not isinstance(state, dict):
                raise RuntimeError("Router cleanup inspect omitted runtime state")
            if state.get("Running") is True:
                _run_docker(provider, ["container", "stop", "--time", "5", router_id])
                current = _inspect_json(
                    provider, ["container", "inspect", "--format", _CLEANUP_CONTAINER_INSPECT_FORMAT, router_id]
                )
                state = current.get("State")
                if (
                    current.get("Id") != router_id
                    or not isinstance(state, dict)
                    or state.get("Running") is not False
                ):
                    raise RuntimeError("Router stop was not confirmed by immutable-ID inspect")
            _run_docker(provider, ["container", "rm", router_id])
            outcome["router_removed"] = True
        elif router_id is not None and not router_owned:
            outcome["detail"] = "Router was observed as pre-existing/concurrent; it was not removed"
            network_owned = False

        if network_id is not None and network_owned:
            if not _RUNTIME_ID.fullmatch(network_id):
                raise RuntimeError("refusing network cleanup without a full immutable ID")
            network = _inspect_json(
                provider, ["network", "inspect", "--format", _CLEANUP_NETWORK_INSPECT_FORMAT, network_id]
            )
            labels = network.get("Labels")
            if (
                network.get("Id") != network_id
                or not isinstance(labels, dict)
                or labels.get("com.ai-team.router.managed") != "true"
                or labels.get("com.ai-team.router.scope-sha256") != scope_fingerprint
            ):
                raise RuntimeError("Network immutable identity/scope changed; cleanup refused")
            _run_docker(provider, ["network", "rm", network_id])
            outcome["network_removed"] = True

        if outcome["detail"]:
            outcome["status"] = "preserved"
        elif router_id is not None and not router_owned:
            outcome["status"] = "preserved"
        elif network_id is not None and not network_owned:
            outcome["status"] = "removed"
        elif (router_id is None or outcome["router_removed"]) and (
            network_id is None or outcome["network_removed"]
        ):
            outcome["status"] = "removed"
        else:
            outcome["status"] = "preserved"
    except Exception as exc:
        outcome["status"] = "failed"
        outcome["detail"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    return outcome


def _diagnostic_command(
    provider: LocalDockerProvider, arguments: list[str]
) -> dict[str, Any]:
    result, error = provider._execute(arguments)
    if error:
        return {"status": "unavailable", "error": type(error).__name__}
    assert result is not None
    return {
        "status": "completed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": (result.stdout or "")[-1200:],
        "stderr": (result.stderr or "")[-1200:],
    }


_ROUTER_CONTRACT_DIAGNOSTIC_FORMAT = (
    r'{{printf "{\"ConfigUser\":%q,\"ReadonlyRootfs\":%t,\"Privileged\":%t,'
    r'\"CapDrop\":%s,\"CapAdd\":%s,\"SecurityOpt\":%s,\"NetworkMode\":%q,'
    r'\"RestartPolicy\":%q,\"Tmpfs\":%s}" .Config.User .HostConfig.ReadonlyRootfs '
    r'.HostConfig.Privileged (json .HostConfig.CapDrop) (json .HostConfig.CapAdd) '
    r'(json .HostConfig.SecurityOpt) .HostConfig.NetworkMode '
    r'.HostConfig.RestartPolicy.Name (json .HostConfig.Tmpfs)}}'
)


def run_live_smoke() -> dict[str, Any]:
    provider = LocalDockerProvider()
    scope = TrafficRouterScope(
        "docker-local",
        "router-live-smoke-" + uuid.uuid4().hex,
        "ci",
    )
    port_bindings = (TrafficPortBinding(_free_tcp_port(), 8080),)
    temp_root = Path(tempfile.mkdtemp(prefix="ai-team-router-live-smoke-"))
    state_root = temp_root / "state"
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "probe": "local_docker_router_live_bootstrap",
        "status": "failed",
        "scope_provider": scope.provider,
        "port_bindings": [
            {
                "host_port": port_bindings[0].host_port,
                "container_port": port_bindings[0].container_port,
                "protocol": "tcp",
            }
        ],
        "checks": {},
    }
    image_id: str | None = None
    network_id: str | None = None
    network_owned = False
    router_id: str | None = None
    router_owned = False
    container_ensure_attempted = False
    scope_fingerprint: str | None = None

    try:
        image = LocalDockerRouterImageManager(provider, Path.cwd()).build_and_verify()
        if image.status != "verified" or image.identity is None:
            raise RuntimeError(f"pinned Router image verification: {image.status}: {image.detail}")
        image_id = image.identity.image_id
        evidence["checks"]["image"] = {
            "status": image.status,
            "image_id": image_id,
            "haproxy_version": image.identity.haproxy_version,
            "socat_package_version": image.identity.socat_package_version,
            "architecture": image.identity.architecture,
        }

        network = LocalDockerRouterNetworkManager(provider).ensure_network(scope)
        if network.status not in {"created", "existing"} or network.record is None:
            raise RuntimeError(f"Router bridge network ensure: {network.status}: {network.detail}")
        network_id = network.record.network_id
        network_owned = network.status == "created"
        scope_fingerprint = network.record.scope_fingerprint
        evidence["checks"]["network"] = {
            "status": network.status,
            "network_id": network_id,
            "network_name": network.record.network_name,
            "scope_fingerprint": scope_fingerprint,
        }

        state = LocalDockerRouterStateStore(state_root).persist(
            scope, port_bindings, active_slot=None
        )
        if state.status != "persisted" or state.record is None:
            raise RuntimeError(f"Router Host state persist: {state.status}: {state.detail}")
        evidence["checks"]["host_state"] = {
            "status": state.status,
            "directory_mode": oct(state.record.directory_mode),
            "file_mode": oct(state.record.file_mode),
            "active_map_sha256": state.record.active_slot_map_sha256,
            "config_sha256": state.record.config_sha256,
        }

        config = LocalDockerRouterConfigValidator(provider).validate(image.identity, state.record)
        if config.status != "valid":
            raise RuntimeError(f"HAProxy generated config validation: {config.status}: {config.detail}")
        evidence["checks"]["config_validation"] = config.status

        spec = build_router_container_spec(
            scope, port_bindings, network.record, image.identity, state.record
        )
        container_ensure_attempted = True
        ensured = LocalDockerRouterContainerManager(provider).ensure_router(spec)
        evidence["checks"]["router_container"] = {
            "status": ensured.status,
            "detail": ensured.detail,
        }
        if ensured.status != "created" or ensured.container_id is None:
            evidence["diagnostics"] = {
                "router_container_inspect": _diagnostic_command(
                    provider,
                    ["container", "inspect", "--format", _ROUTER_CONTRACT_DIAGNOSTIC_FORMAT, spec.container_name],
                )
            }
            if ensured.container_id is not None:
                router_id = ensured.container_id
            raise RuntimeError(
                f"Router container must be newly created and immutable-ID verified; "
                f"observed {ensured.status}: {ensured.detail}"
            )
        router_id = ensured.container_id
        router_owned = True

        client = HAProxyRuntimeAPIClient(provider, router_id)
        info_result = wait_for_runtime_api_show_info(client)
        if info_result.status != "succeeded":
            evidence["diagnostics"] = {
                "runtime_api_stdout": info_result.response[-1200:],
                "runtime_api_stderr": info_result.detail[-1200:],
                "container_user": _diagnostic_command(
                    provider, ["container", "inspect", "--format", "{{.Config.User}}", router_id]
                ),
                "container_logs": _diagnostic_command(
                    provider, ["container", "logs", "--tail", "40", router_id]
                ),
                "process_identity": _diagnostic_command(
                    provider, ["exec", router_id, "id"]
                ),
                "runtime_directory": _diagnostic_command(
                    provider, ["exec", router_id, "ls", "-ld", "/run/haproxy"]
                ),
                "runtime_socket_listing": _diagnostic_command(
                    provider, ["exec", router_id, "ls", "-l", "/run/haproxy"]
                ),
            }
            raise RuntimeError(
                f"HAProxy Runtime API show info: {info_result.status}: {info_result.detail}"
            )
        info = parse_show_info(info_result.response)
        maps_result = client.execute(show_maps_command())
        if maps_result.status != "succeeded":
            raise RuntimeError(
                f"HAProxy Runtime API show map: {maps_result.status}: {maps_result.detail}"
            )
        map_id = parse_show_map_registry(
            maps_result.response, expected_path=HAPROXY_ACTIVE_SLOT_MAP
        )
        map_result = client.execute(get_map_command(map_id, "active"))
        if map_result.status != "succeeded":
            raise RuntimeError(
                f"HAProxy Runtime API get map: {map_result.status}: {map_result.detail}"
            )
        try:
            active_slot = parse_get_map_value(
                map_result.response, expected_key="active", expected_value="none"
            )
        except ValueError:
            evidence["diagnostics"] = {
                "get_map_response": map_result.response[-1600:],
            }
            raise
        if active_slot != "none":
            raise RuntimeError("fresh Router did not load the fail-closed active none selector")

        evidence["checks"]["runtime_api"] = {
            "show_info": "succeeded",
            "process_name": info["Name"],
            "haproxy_version": info["Version"],
            "show_map_registry": "succeeded",
            "map_id": map_id,
            "map_path": HAPROXY_ACTIVE_SLOT_MAP,
            "get_map": "succeeded",
            "active_selector": active_slot,
        }
        evidence["router"] = {
            "runtime_id": router_id,
            "container_name": spec.container_name,
            "image_id": image_id,
            "network_id": network_id,
        }
        evidence["status"] = "ready"
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["failure"] = {
            "type": type(exc).__name__,
            "detail": str(exc)[:800],
        }
    finally:
        safe_to_remove_network = network_owned and (
            not container_ensure_attempted or router_owned
        )
        cleanup = _cleanup_owned_resources(
            provider,
            router_id=router_id,
            router_owned=router_owned,
            network_id=network_id,
            network_owned=safe_to_remove_network,
            scope_fingerprint=scope_fingerprint,
        )
        evidence["cleanup"] = cleanup
        if container_ensure_attempted and not router_owned and network_owned:
            evidence["cleanup"]["status"] = "preserved"
            evidence["cleanup"]["detail"] = (
                "Router create/inspect outcome was ambiguous; created network and Host state preserved"
            )
        if cleanup["status"] == "failed" or (
            evidence["status"] == "ready" and cleanup["status"] != "removed"
        ):
            evidence["status"] = "failed"
        if cleanup["status"] == "removed":
            shutil.rmtree(temp_root, ignore_errors=True)
        else:
            evidence["retained_state_dir"] = str(temp_root)

    return evidence


def main() -> int:
    evidence = run_live_smoke()
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)
    output_path = os.environ.get("AI_TEAM_ROUTER_EVIDENCE_PATH")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if evidence.get("status") == "ready" and evidence.get("cleanup", {}).get("status") == "removed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
