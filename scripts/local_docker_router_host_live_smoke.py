"""Real Docker Engine smoke for Host Router lifecycle create/reload.

The probe creates a unique Router scope through LocalDockerRouterHostManager,
then invokes the same manager again to exercise SQLite-backed state reload.
The second call must inspect existing immutable resources only, preserve the
active selector and state files, and never create/recreate the Router. Cleanup
uses only the immutable container/network IDs returned by the verified create.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.haproxy_runtime_api import (
    HAProxyRuntimeAPIClient,
    get_map_command,
    show_maps_command,
)
from runtime.haproxy_runtime_readback import parse_get_map_value, parse_show_map_registry
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_config import HAPROXY_ACTIVE_SLOT_MAP
from runtime.local_docker_router_host import LocalDockerRouterHostManager
from scripts.local_docker_router_live_smoke import (
    _cleanup_owned_resources,
    parse_show_info,
    wait_for_runtime_api_show_info,
)


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("0.0.0.0", 0))
        return int(listener.getsockname()[1])


def run_live_smoke() -> dict[str, Any]:
    provider = LocalDockerProvider()
    scope = TrafficRouterScope(
        "docker-local",
        "router-host-live-" + uuid.uuid4().hex,
        "ci",
    )
    bindings = (TrafficPortBinding(_free_tcp_port(), 8080),)
    root = Path(tempfile.mkdtemp(prefix="ai-team-router-host-live-"))
    history_path = root / "deployment-history.db"
    state_root = root / "router-state"
    manager = LocalDockerRouterHostManager(
        provider, DeploymentHistoryStore(history_path), Path.cwd(), state_root
    )
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "probe": "local_docker_router_host_lifecycle",
        "status": "failed",
        "scope": {
            "provider": scope.provider,
            "project": scope.project,
            "environment": scope.environment,
        },
        "port_bindings": [
            {
                "host_port": bindings[0].host_port,
                "container_port": bindings[0].container_port,
                "protocol": "tcp",
            }
        ],
        "checks": {},
    }
    router_id: str | None = None
    network_id: str | None = None
    scope_fingerprint: str | None = None
    owned = False
    cleanup: dict[str, Any] = {"status": "not_required"}

    try:
        created = manager.ensure_router(scope, bindings)
        evidence["checks"]["initial_create"] = {
            "status": created.status,
            "detail": created.detail,
        }
        if (
            created.status != "created"
            or created.router_record is None
            or created.state_record is None
            or created.network is None
            or created.image is None
            or created.container_spec is None
        ):
            raise RuntimeError(
                "Host Router first-create did not return fully verified immutable resources: "
                f"{created.status}: {created.detail}"
            )
        router_id = created.router_record.router_runtime_id
        network_id = created.network.network_id
        scope_fingerprint = created.network.scope_fingerprint
        owned = True

        history_record = manager.history.get_traffic_router(scope)
        host_state = manager.history.get_traffic_router_state_record(scope)
        if history_record != created.router_record or host_state != created.state_record:
            raise RuntimeError("SQLite Router registry read-back did not match the created immutable records")

        map_path = Path(created.state_record.active_slot_map_path)
        before_map = map_path.read_bytes()
        before_digest = created.state_record.active_slot_map_sha256
        if before_map != b"active none\n":
            raise RuntimeError("new Host Router scope did not persist the fail-closed active none selector")

        client = HAProxyRuntimeAPIClient(provider, router_id)
        info = wait_for_runtime_api_show_info(client)
        if info.status != "succeeded":
            raise RuntimeError(f"HAProxy Runtime API readiness failed: {info.status}: {info.detail}")
        runtime_info = parse_show_info(info.response)
        maps = client.execute(show_maps_command())
        if maps.status != "succeeded":
            raise RuntimeError(f"HAProxy show map failed: {maps.status}: {maps.detail}")
        map_id = parse_show_map_registry(
            maps.response, expected_path=HAPROXY_ACTIVE_SLOT_MAP
        )
        selector = client.execute(get_map_command(map_id, "active"))
        if selector.status != "succeeded":
            raise RuntimeError(f"HAProxy get map failed: {selector.status}: {selector.detail}")
        active_slot = parse_get_map_value(
            selector.response, expected_key="active", expected_value="none"
        )
        if active_slot != "none":
            raise RuntimeError("newly created Host Router did not load active none")

        evidence["checks"]["runtime_api"] = {
            "status": "passed",
            "haproxy_version": runtime_info["Version"],
            "map_id": map_id,
            "active_selector": active_slot,
        }

        # This is the key restart/reload path: no build, create, adopt, or
        # bootstrap persistence is allowed when the SQLite registry exists.
        reloaded = manager.ensure_router(scope, bindings)
        evidence["checks"]["registry_reload"] = {
            "status": reloaded.status,
            "detail": reloaded.detail,
            "router_runtime_id": (
                reloaded.router_record.router_runtime_id
                if reloaded.router_record is not None else None
            ),
            "image_id": reloaded.image.image_id if reloaded.image is not None else None,
        }
        if (
            reloaded.status != "ready"
            or reloaded.router_record != created.router_record
            or reloaded.state_record != created.state_record
            or reloaded.network is None
            or reloaded.network.network_id != network_id
            or reloaded.image is None
            or reloaded.image.image_id != created.image.image_id
        ):
            raise RuntimeError(
                f"existing Host Router registry reload failed identity/readback checks: "
                f"{reloaded.status}: {reloaded.detail}"
            )
        after_map = map_path.read_bytes()
        if (
            after_map != before_map
            or reloaded.state_record.active_slot_map_sha256 != before_digest
        ):
            raise RuntimeError("existing Router reload rewrote the Host active map or its digest")

        final_selector = client.execute(get_map_command(map_id, "active"))
        if final_selector.status != "succeeded":
            raise RuntimeError("Runtime API selector became unavailable after Host registry reload")
        parse_get_map_value(
            final_selector.response, expected_key="active", expected_value="none"
        )
        evidence["checks"]["host_state_unchanged"] = {
            "status": "passed",
            "active_map_sha256": before_digest,
            "active_map_bytes_unchanged": True,
        }
        evidence["router"] = {
            "runtime_id": router_id,
            "image_id": created.image.image_id,
            "network_id": network_id,
            "network_name": created.network.network_name,
            "container_name": created.container_spec.container_name,
        }
        evidence["status"] = "ready"
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["failure"] = {
            "type": type(exc).__name__,
            "detail": str(exc)[:1000],
        }
    finally:
        if owned and router_id is not None and network_id is not None and scope_fingerprint is not None:
            cleanup = _cleanup_owned_resources(
                provider,
                router_id=router_id,
                router_owned=True,
                network_id=network_id,
                network_owned=True,
                scope_fingerprint=scope_fingerprint,
            )
        evidence["cleanup"] = cleanup
        if (
            evidence["status"] == "ready"
            and cleanup.get("status") != "removed"
        ):
            evidence["status"] = "failed"
        if cleanup.get("status") == "removed":
            shutil.rmtree(root, ignore_errors=True)
        else:
            evidence["retained_state_dir"] = str(root)

    return evidence


def main() -> int:
    evidence = run_live_smoke()
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)
    output_path = os.environ.get("AI_TEAM_ROUTER_HOST_EVIDENCE_PATH")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if evidence.get("status") == "ready" and evidence.get("cleanup", {}).get("status") == "removed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
