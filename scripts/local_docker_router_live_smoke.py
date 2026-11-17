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
import uuid
from pathlib import Path
from typing import Any

from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.haproxy_runtime_api import (
    HAProxyRuntimeAPIClient,
    get_map_command,
    show_info_command,
)
from runtime.local_docker_provider import LocalDockerProvider
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


def parse_get_map_value(response: str, *, expected_key: str) -> str:
    """Parse the structured get-map response; reject missing/ambiguous fields."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("HAProxy get map returned an empty response")
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("HAProxy get map must return exactly one result line")
    fields: dict[str, str] = {}
    for item in lines[0].split(","):
        key, separator, raw_value = item.partition("=")
        key = key.strip()
        raw_value = raw_value.strip()
        if not separator or not key or key in fields or not raw_value:
            raise ValueError("HAProxy get map returned malformed or duplicate fields")
        if raw_value.startswith('"'):
            if len(raw_value) < 2 or not raw_value.endswith('"'):
                raise ValueError("HAProxy get map returned an unterminated quoted field")
            value = raw_value[1:-1]
        else:
            value = raw_value
        fields[key] = value
    if fields.get("found") != "yes" or fields.get("key") != expected_key:
        raise ValueError("HAProxy get map did not confirm the requested key")
    value = fields.get("value")
    if not value:
        raise ValueError("HAProxy get map omitted the selector value")
    return value


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
                provider, ["container", "inspect", "--format", "{{json .}}", router_id]
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
                    provider, ["container", "inspect", "--format", "{{json .}}", router_id]
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
                provider, ["network", "inspect", "--format", "{{json .}}", network_id]
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
            if ensured.container_id is not None:
                router_id = ensured.container_id
            raise RuntimeError(
                f"Router container must be newly created and immutable-ID verified; "
                f"observed {ensured.status}: {ensured.detail}"
            )
        router_id = ensured.container_id
        router_owned = True

        client = HAProxyRuntimeAPIClient(provider, router_id)
        info_result = client.execute(show_info_command())
        if info_result.status != "succeeded":
            raise RuntimeError(
                f"HAProxy Runtime API show info: {info_result.status}: {info_result.detail}"
            )
        info = parse_show_info(info_result.response)
        map_result = client.execute(
            get_map_command(state.record.active_slot_map_path, "active")
        )
        if map_result.status != "succeeded":
            raise RuntimeError(
                f"HAProxy Runtime API get map: {map_result.status}: {map_result.detail}"
            )
        active_slot = parse_get_map_value(map_result.response, expected_key="active")
        if active_slot != "none":
            raise RuntimeError("fresh Router did not load the fail-closed active none selector")

        evidence["checks"]["runtime_api"] = {
            "show_info": "succeeded",
            "process_name": info["Name"],
            "haproxy_version": info["Version"],
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
