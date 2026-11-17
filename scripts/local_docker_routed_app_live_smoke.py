"""Live Docker Engine acceptance for the Host-owned routed-app manager.

Builds a tiny socat TCP service from the already verified Router base image,
creates one container on a unique verified scope bridge, confirms private
network identity and fresh Docker HEALTHCHECK, and verifies there is no host
port binding. It never publishes an app port, switches the Router map, or
retires a deployment. Cleanup is by verified immutable IDs only.
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

from runtime.deployment_provider import DeploymentArtifact
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_image import LocalDockerRouterImageManager, ROUTER_IMAGE_TAG
from runtime.local_docker_router_network import LocalDockerRouterNetworkManager
from runtime.local_docker_routed_app import (
    LocalDockerRoutedAppManager,
    build_routed_app_container_spec,
)

_RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_APP_MANAGED_LABEL = "com.ai-team.router.routed-app.managed"
_SCOPE_LABEL = "com.ai-team.router.scope-sha256"
_NETWORK_ID_LABEL = "com.ai-team.router.network-id"
_DEPLOYMENT_LABEL = "com.ai-team.router.deployment-id"
_IMAGE_ID_LABEL = "com.ai-team.router.image-id"

_APP_CLEANUP_INSPECT_FORMAT = (
    r'{{printf "{\"Id\":%q,\"Labels\":%s,\"Status\":%q}" '
    r'.Id (json .Config.Labels) .State.Status}}'
)
_NETWORK_CLEANUP_INSPECT_FORMAT = (
    r'{{printf "{\"Id\":%q,\"Labels\":%s}" .Id (json .Labels)}}'
)


def _run_docker(provider: LocalDockerProvider, arguments: list[str]) -> str:
    result, error = provider._execute(arguments)
    if error:
        raise RuntimeError(f"Docker command unavailable: {type(error).__name__}")
    assert result is not None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Docker command failed").strip()
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


def cleanup_owned_app_container(
    provider: LocalDockerProvider,
    *,
    runtime_id: str | None,
    owned: bool,
    scope_fingerprint: str,
    network_id: str,
    deployment_id: str,
    image_id: str,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "status": "not_required",
        "container_removed": False,
        "detail": "",
    }
    if runtime_id is None:
        return outcome
    if not owned:
        return {
            "status": "preserved",
            "container_removed": False,
            "detail": "Routed app was pre-existing or its create outcome was ambiguous; not removed",
        }
    try:
        if not _RUNTIME_ID.fullmatch(runtime_id):
            raise RuntimeError("refusing app cleanup without a full immutable container ID")
        current = _inspect_json(
            provider, [
                "container", "inspect", "--format",
                _APP_CLEANUP_INSPECT_FORMAT, runtime_id,
            ]
        )
        labels = current.get("Labels")
        if (
            current.get("Id") != runtime_id
            or not isinstance(labels, dict)
            or labels.get(_APP_MANAGED_LABEL) != "true"
            or labels.get(_SCOPE_LABEL) != scope_fingerprint
            or labels.get(_NETWORK_ID_LABEL) != network_id
            or labels.get(_DEPLOYMENT_LABEL) != deployment_id
            or labels.get(_IMAGE_ID_LABEL) != image_id
        ):
            raise RuntimeError("app immutable identity or managed scope changed; cleanup refused")
        state = current.get("Status")
        if state == "running":
            _run_docker(provider, ["container", "stop", "--time", "5", runtime_id])
            current = _inspect_json(
                provider, [
                    "container", "inspect", "--format",
                    _APP_CLEANUP_INSPECT_FORMAT, runtime_id,
                ]
            )
            labels = current.get("Labels")
            if (
                current.get("Id") != runtime_id
                or not isinstance(labels, dict)
                or labels.get(_APP_MANAGED_LABEL) != "true"
                or labels.get(_SCOPE_LABEL) != scope_fingerprint
                or labels.get(_NETWORK_ID_LABEL) != network_id
                or labels.get(_DEPLOYMENT_LABEL) != deployment_id
                or labels.get(_IMAGE_ID_LABEL) != image_id
                or current.get("Status") != "exited"
            ):
                raise RuntimeError("app stop was not confirmed by immutable-ID inspect")
        elif state != "exited":
            raise RuntimeError("app cleanup encountered an unrecognized container state")
        _run_docker(provider, ["container", "rm", runtime_id])
        outcome["container_removed"] = True
        outcome["status"] = "removed"
    except Exception as exc:
        outcome["status"] = "failed"
        outcome["detail"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    return outcome


def cleanup_owned_network(
    provider: LocalDockerProvider,
    *,
    network_id: str | None,
    owned: bool,
    scope_fingerprint: str | None,
    app_cleanup_status: str,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "status": "not_required",
        "network_removed": False,
        "detail": "",
    }
    if network_id is None:
        return outcome
    if not owned:
        return {
            "status": "preserved",
            "network_removed": False,
            "detail": "Network was not created by this smoke; it was not removed",
        }
    if app_cleanup_status not in {"removed", "not_required"}:
        return {
            "status": "preserved",
            "network_removed": False,
            "detail": "App cleanup was not confirmed; network preserved",
        }
    try:
        if not _RUNTIME_ID.fullmatch(network_id) or not isinstance(scope_fingerprint, str):
            raise RuntimeError("refusing network cleanup without verified immutable scope identity")
        network = _inspect_json(
            provider, [
                "network", "inspect", "--format",
                _NETWORK_CLEANUP_INSPECT_FORMAT, network_id,
            ]
        )
        labels = network.get("Labels")
        if (
            network.get("Id") != network_id
            or not isinstance(labels, dict)
            or labels.get("com.ai-team.router.managed") != "true"
            or labels.get(_SCOPE_LABEL) != scope_fingerprint
        ):
            raise RuntimeError("network immutable identity or scope changed; cleanup refused")
        _run_docker(provider, ["network", "rm", network_id])
        outcome["network_removed"] = True
        outcome["status"] = "removed"
    except Exception as exc:
        outcome["status"] = "failed"
        outcome["detail"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    return outcome


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("0.0.0.0", 0))
        return int(listener.getsockname()[1])


def run_live_smoke() -> dict[str, Any]:
    provider = LocalDockerProvider()
    scope = TrafficRouterScope(
        "docker-local",
        "routed-app-live-smoke-" + uuid.uuid4().hex,
        "ci",
    )
    deployment_id = "app-" + uuid.uuid4().hex[:20]
    host_port = _free_tcp_port()
    port_bindings = (TrafficPortBinding(host_port, 18080),)
    temp_root = Path(tempfile.mkdtemp(prefix="ai-team-routed-app-live-smoke-"))
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "probe": "local_docker_routed_app_live_smoke",
        "status": "failed",
        "scope_provider": scope.provider,
        "port_bindings": [
            {
                "host_port": host_port,
                "container_port": 18080,
                "protocol": "tcp",
                "host_port_published_by_app": False,
            }
        ],
        "checks": {},
    }
    network_id: str | None = None
    network_owned = False
    scope_fingerprint: str | None = None
    app_id: str | None = None
    app_owned = False
    app_attempted = False
    app_image_id: str | None = None
    app_tag: str | None = None

    try:
        base = LocalDockerRouterImageManager(provider, Path.cwd()).build_and_verify()
        if base.status != "verified" or base.identity is None:
            raise RuntimeError(f"pinned Router base image: {base.status}: {base.detail}")
        evidence["checks"]["router_base_image"] = {
            "status": base.status,
            "image_id": base.identity.image_id,
            "haproxy_version": base.identity.haproxy_version,
            "socat_package_version": base.identity.socat_package_version,
        }

        context = Path("docker") / "routed-app-smoke"
        if not (context / "Dockerfile").is_file():
            raise RuntimeError("routed-app smoke Dockerfile is missing")
        app_tag = "ai-team/routed-app-smoke:" + uuid.uuid4().hex[:16]
        build_result, build_error = provider._execute(
            [
                "build", "--file", "Dockerfile",
                "--build-arg", f"ROUTER_BASE_IMAGE={ROUTER_IMAGE_TAG}",
                "--tag", app_tag, ".",
            ],
            cwd=str(context),
        )
        if build_error:
            raise RuntimeError(f"routed-app smoke image build unavailable: {type(build_error).__name__}")
        assert build_result is not None
        if build_result.returncode != 0:
            detail = (build_result.stderr or build_result.stdout or "Docker build failed").strip()
            raise RuntimeError(f"routed-app smoke image build failed: {detail[-700:]}")
        image_result = _run_docker(
            provider, ["image", "inspect", "--format", "{{.Id}}", app_tag]
        ).strip()
        if not _IMAGE_ID.fullmatch(image_result):
            raise RuntimeError("routed-app smoke image inspect did not return a full immutable ID")
        app_image_id = image_result
        evidence["checks"]["app_image"] = {
            "status": "built_and_inspected",
            "image_id": app_image_id,
            "tag": app_tag,
            "base_image_tag": ROUTER_IMAGE_TAG,
        }

        network = LocalDockerRouterNetworkManager(provider).ensure_network(scope)
        if network.status != "created" or network.record is None:
            raise RuntimeError(
                f"smoke requires a newly created isolated bridge; "
                f"observed {network.status}: {network.detail}"
            )
        network_id = network.record.network_id
        network_owned = True
        scope_fingerprint = network.record.scope_fingerprint
        evidence["checks"]["network"] = {
            "status": network.status,
            "network_id": network_id,
            "network_name": network.record.network_name,
            "scope_fingerprint": scope_fingerprint,
        }

        artifact = DeploymentArtifact(
            "docker-local", app_tag, app_image_id.removeprefix("sha256:"), "live-smoke"
        )
        app_spec = build_routed_app_container_spec(
            network.record, artifact, deployment_id, port_bindings
        )
        manager = LocalDockerRoutedAppManager(provider)
        app_attempted = True
        ensured = manager.ensure_app(app_spec, artifact)
        if ensured.status not in {"created", "existing"} or ensured.target is None:
            raise RuntimeError(
                f"routed app ensure: {ensured.status}: {ensured.detail or ensured.health_detail}"
            )
        app_id = ensured.target.runtime_id
        app_owned = ensured.status == "created"
        first_status = ensured.status

        for attempt in range(40):
            if ensured.route_eligible:
                break
            if attempt == 39:
                break
            time.sleep(0.25)
            refreshed = manager.ensure_app(app_spec, artifact)
            if (
                refreshed.status not in {"created", "existing"}
                or refreshed.target is None
                or refreshed.target.runtime_id != app_id
            ):
                raise RuntimeError(
                    f"routed app health/read-back changed: "
                    f"{refreshed.status}: {refreshed.detail or refreshed.health_detail}"
                )
            ensured = refreshed
        evidence["checks"]["routed_app"] = {
            "status": ensured.status,
            "first_observed_status": first_status,
            "runtime_id": app_id,
            "network_address": ensured.target.address,
            "health_status": ensured.health_status,
            "route_eligible": ensured.route_eligible,
            "host_port_bindings": "none",
            "detail": ensured.health_detail,
        }
        if not ensured.route_eligible:
            raise RuntimeError(
                f"routed app did not become freshly healthy: "
                f"{ensured.health_status}: {ensured.health_detail}"
            )
        evidence["status"] = "ready"
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["failure"] = {
            "type": type(exc).__name__,
            "detail": str(exc)[:800],
        }
    finally:
        if app_attempted:
            if app_id is None:
                app_cleanup = {
                    "status": "preserved",
                    "container_removed": False,
                    "detail": "App create outcome did not produce a trusted immutable ID; network preserved",
                }
            else:
                app_cleanup = cleanup_owned_app_container(
                    provider,
                    runtime_id=app_id,
                    owned=app_owned,
                    scope_fingerprint=scope_fingerprint or "",
                    network_id=network_id or "",
                    deployment_id=deployment_id,
                    image_id=app_image_id or "",
                )
        else:
            app_cleanup = {
                "status": "not_required",
                "container_removed": False,
                "detail": "",
            }
        network_cleanup = cleanup_owned_network(
            provider,
            network_id=network_id,
            owned=network_owned,
            scope_fingerprint=scope_fingerprint,
            app_cleanup_status=app_cleanup["status"],
        )
        evidence["cleanup"] = {
            "app": app_cleanup,
            "network": network_cleanup,
            "status": (
                "removed"
                if app_cleanup["status"] in {"removed", "not_required"}
                and network_cleanup["status"] in {"removed", "not_required"}
                else "preserved" if "failed" not in {
                    app_cleanup["status"], network_cleanup["status"]
                } else "failed"
            ),
        }
        if evidence["cleanup"]["status"] != "removed":
            evidence["status"] = "failed"
        if evidence["cleanup"]["status"] == "removed":
            shutil.rmtree(temp_root, ignore_errors=True)
        else:
            evidence["retained_state_dir"] = str(temp_root)

    return evidence


def main() -> int:
    evidence = run_live_smoke()
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)
    output_path = os.environ.get("AI_TEAM_ROUTED_APP_EVIDENCE_PATH")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if evidence.get("status") == "ready" and evidence.get("cleanup", {}).get("status") == "removed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
