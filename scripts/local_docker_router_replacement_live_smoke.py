"""Daemon-backed Local Docker Router blue-green replacement acceptance.

Creates one Router scope and two distinct TCP marker apps. The old app is
activated first; the replacement provider then starts the second app on the
same private bridge and container port, proves both are healthy while the old
selector remains live, switches the Router, drains the old slot to MAINT with
zero current sessions, and stops the old immutable container ID.

On any ambiguous failure, resources and Host state are preserved for manual
inspection. Cleanup runs only after every replacement postcondition is proven.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import (
    DeploymentArtifact,
    DeploymentRecord,
    DeploymentRequest,
)
from runtime.deployment_replacement_manager import HostDeploymentReplacementManager
from runtime.deployment_traffic_router import (
    TrafficPortBinding,
    TrafficRouterScope,
)
from runtime.haproxy_runtime_api import (
    HAProxyRuntimeAPIClient,
    get_map_command,
    show_maps_command,
    show_stat_servers_command,
)
from runtime.haproxy_runtime_readback import (
    parse_get_map_value,
    parse_show_map_registry,
    parse_show_stat_servers,
)
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_routed_app import (
    LocalDockerRoutedAppManager,
    build_routed_app_container_spec,
)
from runtime.local_docker_router_config import HAPROXY_ACTIVE_SLOT_MAP
from runtime.local_docker_router_container import build_router_container_spec
from runtime.local_docker_router_host import LocalDockerRouterHostManager
from runtime.local_docker_router_slot_manager import LocalDockerRouterSlotManager
from scripts.local_docker_routed_app_live_smoke import (
    _free_tcp_port,
    _probe_router_tcp_route,
    _run_docker,
    cleanup_owned_app_container,
    cleanup_owned_network,
    cleanup_owned_router_container,
)

_MARKER_A = b"ROUTED_APP_A"
_MARKER_B = b"ROUTED_APP_B"
_APP_CONTEXT = Path("docker") / "routed-app-smoke"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_app_image(
    provider: LocalDockerProvider,
    *,
    base_image_id: str,
    marker: str,
    tag: str,
) -> tuple[str, str]:
    if marker not in {"ROUTED_APP_A", "ROUTED_APP_B"}:
        raise ValueError("app marker is outside the fixed smoke allowlist")
    if not tag.startswith("ai-team/router-replacement-smoke:"):
        raise ValueError("smoke image tag is outside the fixed namespace")
    result, error = provider._execute(
        [
            "build", "--file", "Dockerfile",
            "--build-arg", f"ROUTER_BASE_IMAGE={base_image_id}",
            "--build-arg", f"APP_MARKER={marker}",
            "--tag", tag, ".",
        ],
        cwd=str(_APP_CONTEXT),
    )
    if error:
        raise RuntimeError(f"routed app image build unavailable: {type(error).__name__}")
    assert result is not None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Docker build failed").strip()
        raise RuntimeError(f"routed app image build failed: {detail[-700:]}")
    image_id = _run_docker(
        provider, ["image", "inspect", "--format", "{{.Id}}", tag]
    ).strip()
    if len(image_id) != 71 or not image_id.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in image_id[7:]
    ):
        raise RuntimeError("routed app image inspect did not return a full immutable image ID")
    return tag, image_id


def _ensure_healthy_app(
    manager: LocalDockerRoutedAppManager,
    spec,
    artifact: DeploymentArtifact,
):
    first = manager.ensure_app(spec, artifact)
    if first.status not in {"created", "existing"} or first.target is None:
        raise RuntimeError(
            f"routed app ensure failed: {first.status}: {first.detail or first.health_detail}"
        )
    result = first
    for attempt in range(40):
        if result.route_eligible:
            return first.status, result
        if attempt + 1 == 40:
            break
        time.sleep(0.25)
        result = manager.ensure_app(spec, artifact)
        if (
            result.status not in {"created", "existing"}
            or result.target is None
            or result.target.runtime_id != first.target.runtime_id
        ):
            raise RuntimeError(
                f"routed app identity changed during health wait: "
                f"{result.status}: {result.detail or result.health_detail}"
            )
    raise RuntimeError(
        f"routed app did not become healthy: {result.health_status}: {result.health_detail}"
    )


class _EvidenceSlotManager(LocalDockerRouterSlotManager):
    """Capture the real coexistence point after candidate prepare, before switch."""

    def __init__(
        self,
        provider: LocalDockerProvider,
        app_manager: LocalDockerRoutedAppManager,
        previous_spec,
        host_port: int,
        evidence: dict[str, Any],
    ) -> None:
        super().__init__(provider, readback_attempts=24, readback_interval_seconds=0.25)
        self.app_manager = app_manager
        self.previous_spec = previous_spec
        self.host_port = host_port
        self.evidence = evidence

    def prepare_inactive_slot(self, **kwargs):
        result = super().prepare_inactive_slot(**kwargs)
        if result.status != "verified":
            return result
        old_status, old_verification, old_detail = self.app_manager._inspect(
            self.previous_spec
        )
        new_status, new_verification, new_detail = self.app_manager._inspect(
            kwargs["app_spec"]
        )
        if (
            old_status != "verified"
            or old_verification is None
            or not old_verification.route_eligible
            or old_verification.target is None
            or new_status != "verified"
            or new_verification is None
            or not new_verification.route_eligible
            or new_verification.target is None
            or old_verification.target.runtime_id == new_verification.target.runtime_id
        ):
            raise RuntimeError(
                "two-app coexistence read-back failed: "
                f"old={old_status}:{old_detail}; new={new_status}:{new_detail}"
            )
        old_marker = _probe_router_tcp_route(
            self.host_port, expected_marker=_MARKER_A
        )
        if old_marker.get("status") != "passed":
            raise RuntimeError("old app stopped serving before Router cutover")
        self.evidence["checks"]["two_app_coexistence"] = {
            "status": "verified",
            "old_runtime_id": old_verification.target.runtime_id,
            "candidate_runtime_id": new_verification.target.runtime_id,
            "old_app_health": old_verification.health_status,
            "candidate_app_health": new_verification.health_status,
            "old_app_marker_before_switch": old_marker,
            "both_apps_share_scope_bridge": True,
            "same_container_port": True,
            "app_host_port_bindings": "none",
            "active_selector_before_switch": result.active_selector_before,
            "active_selector_after_prepare": result.active_selector_after,
        }
        if (
            result.active_selector_before != "slot_a"
            or result.active_selector_after != "slot_a"
        ):
            raise RuntimeError("inactive candidate preparation changed the active selector")
        return result


def _runtime_selector(
    provider: LocalDockerProvider, router_id: str
) -> str:
    client = HAProxyRuntimeAPIClient(provider, router_id)
    maps = client.execute(show_maps_command())
    if maps.status != "succeeded":
        raise RuntimeError(f"HAProxy show map failed: {maps.detail}")
    map_id = parse_show_map_registry(
        maps.response, expected_path=HAPROXY_ACTIVE_SLOT_MAP
    )
    value = client.execute(get_map_command(map_id, "active"))
    if value.status != "succeeded":
        raise RuntimeError(f"HAProxy get map failed: {value.detail}")
    return parse_get_map_value(value.response, expected_key="active")


def run_live_smoke() -> dict[str, Any]:
    provider = LocalDockerProvider()
    project = "router-replacement-" + uuid.uuid4().hex[:16]
    scope = TrafficRouterScope("docker-local", project, "ci")
    host_port = _free_tcp_port()
    bindings = (TrafficPortBinding(host_port, 18080),)
    previous_id = "app-a-" + uuid.uuid4().hex[:16]
    candidate_id = "app-b-" + uuid.uuid4().hex[:16]
    tag_suffix = uuid.uuid4().hex[:12]
    temp_root = Path(tempfile.mkdtemp(prefix="ai-team-router-replacement-"))
    history_path = temp_root / "history.db"
    state_root = temp_root / "router-state"
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "probe": "local_docker_router_replacement_live_smoke",
        "status": "failed",
        "scope": {
            "provider": scope.provider,
            "project": scope.project,
            "environment": scope.environment,
        },
        "port_bindings": [{
            "host_port": host_port,
            "container_port": 18080,
            "protocol": "tcp",
            "host_port_published_by_apps": False,
        }],
        "checks": {},
    }
    router_id: str | None = None
    router_owned = False
    router_attempted = False
    router_image_id: str | None = None
    network_id: str | None = None
    scope_fingerprint: str | None = None
    app_a_id: str | None = None
    app_b_id: str | None = None
    app_a_image_id: str | None = None
    app_b_image_id: str | None = None
    app_a_tag: str | None = None
    app_b_tag: str | None = None
    network_owned = False
    app_a_owned = False
    app_b_owned = False
    completed = False

    try:
        history = DeploymentHistoryStore(history_path)
        router_host = LocalDockerRouterHostManager(
            provider, history, Path.cwd(), state_root
        )
        host = router_host.ensure_router(scope, bindings)
        if (
            host.status != "created"
            or host.router_record is None
            or host.state_record is None
            or host.network is None
            or host.image is None
            or host.container_spec is None
        ):
            raise RuntimeError(
                f"Router Host bootstrap must create a fresh scope: {host.status}: {host.detail}"
            )
        router_id = host.router_record.router_runtime_id
        router_owned = True
        router_attempted = True
        router_image_id = host.image.image_id
        network_id = host.network.network_id
        scope_fingerprint = host.network.scope_fingerprint
        network_owned = True
        evidence["checks"]["router_host_bootstrap"] = {
            "status": host.status,
            "router_runtime_id": router_id,
            "router_image_id": router_image_id,
            "network_id": network_id,
            "state_directory": host.state_record.directory,
            "initial_active_selector": "none",
        }

        app_a_tag, app_a_image_id = _build_app_image(
            provider,
            base_image_id=router_image_id,
            marker="ROUTED_APP_A",
            tag=f"ai-team/router-replacement-smoke:{tag_suffix}-a",
        )
        app_b_tag, app_b_image_id = _build_app_image(
            provider,
            base_image_id=router_image_id,
            marker="ROUTED_APP_B",
            tag=f"ai-team/router-replacement-smoke:{tag_suffix}-b",
        )
        artifact_a = DeploymentArtifact(
            "docker-local", app_a_tag, app_a_image_id[7:], "1.0"
        )
        artifact_b = DeploymentArtifact(
            "docker-local", app_b_tag, app_b_image_id[7:], "2.0"
        )
        app_manager = LocalDockerRoutedAppManager(provider)

        app_a_spec = build_routed_app_container_spec(
            host.network, artifact_a, previous_id, bindings
        )
        app_a_owned_status, app_a = _ensure_healthy_app(
            app_manager, app_a_spec, artifact_a
        )
        if app_a_owned_status != "created":
            raise RuntimeError("old app smoke container must be newly created, not adopted")
        app_a_id = app_a.target.runtime_id
        app_a_owned = True
        evidence["checks"]["old_app"] = {
            "status": "healthy",
            "runtime_id": app_a_id,
            "image_id": app_a_image_id,
            "network_address": app_a.target.address,
            "marker": "ROUTED_APP_A",
            "host_port_bindings": "none",
        }

        bootstrap_slots = LocalDockerRouterSlotManager(
            provider, readback_attempts=24, readback_interval_seconds=0.25
        )
        prepared_a = bootstrap_slots.prepare_inactive_slot(
            router_runtime_id=router_id,
            router_spec=host.container_spec,
            network=host.network,
            app_spec=app_a_spec,
            target=app_a.target,
            slot="slot_a",
            state_record=host.state_record,
        )
        if prepared_a.status != "verified" or prepared_a.state_record is None:
            raise RuntimeError(
                f"initial slot_a preparation failed: {prepared_a.status}: {prepared_a.detail}"
            )
        registered = replace(
            host.router_record,
            slot_targets=(("slot_a", app_a.target),),
            route_generation=uuid.uuid4().hex,
        )
        registered = history.update_traffic_router(
            registered,
            prepared_a.state_record,
            expected_generation=host.router_record.route_generation,
            expected_state_map_sha256=host.state_record.active_slot_map_sha256,
        )
        prepared_router_spec = build_router_container_spec(
            scope, bindings, host.network, host.image, prepared_a.state_record,
            expected_active_slot=None,
        )
        switched_a = bootstrap_slots.switch_active_slot(
            router_runtime_id=router_id,
            router_spec=prepared_router_spec,
            network=host.network,
            app_spec=app_a_spec,
            target=app_a.target,
            slot="slot_a",
            expected_active_slot=None,
            state_record=prepared_a.state_record,
        )
        if switched_a.status != "verified" or switched_a.state_record is None:
            raise RuntimeError(
                f"initial slot_a activation failed: {switched_a.status}: {switched_a.detail}"
            )
        active_router = replace(
            registered,
            active_slot="slot_a",
            active_target=app_a.target,
            route_generation=uuid.uuid4().hex,
        )
        active_router = history.update_traffic_router(
            active_router,
            switched_a.state_record,
            expected_generation=registered.route_generation,
            expected_state_map_sha256=prepared_a.state_record.active_slot_map_sha256,
        )
        record_a = DeploymentRecord(
            deployment_id=previous_id,
            provider="docker-local",
            project=scope.project,
            environment=scope.environment,
            version="1.0",
            artifact=artifact_a,
            status="running",
            health_status="healthy",
            created_at=_now(),
            endpoint=f"tcp://127.0.0.1:{host_port}",
            container_id=app_a_id,
        )
        history.append(record_a)
        history.set_active_deployment(
            provider="docker-local",
            project=scope.project,
            environment=scope.environment,
            deployment_id=previous_id,
            expected_deployment_id=None,
        )
        initial_route = _probe_router_tcp_route(
            host_port, expected_marker=_MARKER_A
        )
        if initial_route.get("status") != "passed":
            raise RuntimeError("initial slot_a marker was not served through Router")
        evidence["checks"]["initial_route"] = {
            "status": "passed",
            "active_slot": "slot_a",
            "runtime_id": app_a_id,
            "tcp_probe": initial_route,
        }

        # Candidate image B is already built, but its app container is created
        # only inside the replacement provider after the coordinator journals
        # and reserves the replacement operation.
        candidate = DeploymentRecord(
            deployment_id=candidate_id,
            provider="docker-local",
            project=scope.project,
            environment=scope.environment,
            version="2.0",
            artifact=artifact_b,
            status="prepared",
            health_status="unknown",
            created_at=_now(),
        )
        request = DeploymentRequest(
            project_root=str(Path.cwd()),
            project=scope.project,
            environment=scope.environment,
            version="2.0",
            ports=(f"{host_port}:18080",),
        )
        evidence_slots = _EvidenceSlotManager(
            provider, app_manager, app_a_spec, host_port, evidence
        )
        replacement_provider = __import__(
            "runtime.local_docker_router_replacement_provider",
            fromlist=["LocalDockerRouterReplacementProvider"],
        ).LocalDockerRouterReplacementProvider(
            provider, history, router_host, app_manager, evidence_slots,
            scope, bindings,
        )
        replacement_manager = HostDeploymentReplacementManager(
            replacement_provider, history
        )
        replacement = replacement_manager.replace(request, candidate)
        evidence["checks"]["replacement_coordinator"] = {
            "status": replacement.status,
            "phase": replacement.phase,
            "operation_id": replacement.operation_id,
            "message": replacement.message,
        }
        if (
            replacement.status != "replaced"
            or replacement.phase != "previous_retired"
            or replacement.record is None
            or replacement.record.deployment_id != candidate_id
        ):
            raise RuntimeError(
                "durable replacement did not reach previous_retired: "
                f"{replacement.status}/{replacement.phase}: {replacement.message}"
            )
        app_b_id = replacement.record.container_id
        if app_b_id is None or app_b_id == app_a_id:
            raise RuntimeError("replacement candidate did not receive a distinct immutable runtime ID")
        operation_context = replacement_provider._operations.get(replacement.operation_id or "")
        app_b_owned = bool(
            operation_context
            and operation_context.get("app_ensure_status") == "created"
        )
        if not app_b_owned:
            raise RuntimeError("candidate app was not confirmed newly created by the routed-app manager")

        selector = _runtime_selector(provider, router_id)
        if selector != "slot_b":
            raise RuntimeError(f"Router Runtime API active selector is {selector}, expected slot_b")
        effective_target = replacement_provider.read_traffic_target(request)
        if effective_target != app_b_id:
            raise RuntimeError("Router live read-back does not resolve to candidate immutable runtime ID")
        marker_b = _probe_router_tcp_route(
            host_port, expected_marker=_MARKER_B
        )
        if marker_b.get("status") != "passed":
            raise RuntimeError("candidate ROUTED_APP_B marker was not served through Router")

        old_record = history.get(previous_id)
        new_record = history.get(candidate_id)
        if old_record is None or old_record.status != "stopped" or old_record.container_id != app_a_id:
            raise RuntimeError("old deployment history does not confirm the previous immutable runtime stopped")
        if new_record is None or new_record.status != "running" or new_record.container_id != app_b_id:
            raise RuntimeError("candidate deployment history does not confirm the new immutable runtime running")
        old_inspection = provider.inspect_runtime(old_record)
        new_inspection = provider.inspect_runtime(new_record)
        if (
            old_inspection.status != "verified"
            or old_inspection.observed_runtime_id != app_a_id
            or old_inspection.runtime_state != "exited"
            or new_inspection.status != "verified"
            or new_inspection.observed_runtime_id != app_b_id
            or new_inspection.runtime_state != "running"
        ):
            raise RuntimeError("Docker immutable-ID inspect did not confirm old exited/new running")
        router_record = history.get_traffic_router(scope)
        if (
            router_record is None
            or router_record.active_slot != "slot_b"
            or router_record.active_target is None
            or router_record.active_target.runtime_id != app_b_id
            or tuple(slot for slot, _ in router_record.slot_targets) != ("slot_b",)
        ):
            raise RuntimeError("durable Router registry does not contain only the active candidate slot")

        stat_result = HAProxyRuntimeAPIClient(provider, router_id).execute(
            show_stat_servers_command(f"be_p{host_port}")
        )
        if stat_result.status != "succeeded":
            raise RuntimeError(f"HAProxy post-retirement show stat failed: {stat_result.detail}")
        stats = parse_show_stat_servers(stat_result.response)
        old_stat = next((item for item in stats if item.server == "slot_a"), None)
        new_stat = next((item for item in stats if item.server == "slot_b"), None)
        if (
            old_stat is None or old_stat.status != "MAINT" or old_stat.current_sessions != 0
            or new_stat is None or new_stat.status != "UP"
        ):
            raise RuntimeError("HAProxy did not confirm old slot MAINT/zero sessions and candidate UP")
        evidence["checks"]["post_replacement"] = {
            "status": "verified",
            "active_selector": selector,
            "effective_runtime_id": effective_target,
            "tcp_marker": marker_b,
            "old_runtime": {
                "runtime_id": app_a_id,
                "deployment_status": old_record.status,
                "docker_state": old_inspection.runtime_state,
                "backend_status": old_stat.status,
                "current_sessions": old_stat.current_sessions,
            },
            "candidate_runtime": {
                "runtime_id": app_b_id,
                "deployment_status": new_record.status,
                "docker_state": new_inspection.runtime_state,
                "backend_status": new_stat.status,
                "current_sessions": new_stat.current_sessions,
            },
            "router_registry_active_slot": router_record.active_slot,
            "router_registry_slot_inventory": [slot for slot, _ in router_record.slot_targets],
        }
        evidence["status"] = "ready"
        completed = True
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["failure"] = {
            "type": type(exc).__name__,
            "detail": str(exc)[:1000],
        }
    finally:
        if completed and router_id and network_id and scope_fingerprint and router_image_id and app_a_id and app_b_id and app_a_image_id and app_b_image_id:
            app_a_cleanup = cleanup_owned_app_container(
                provider, runtime_id=app_a_id, owned=app_a_owned,
                scope_fingerprint=scope_fingerprint, network_id=network_id,
                deployment_id=previous_id, image_id=app_a_image_id,
            )
            app_b_cleanup = cleanup_owned_app_container(
                provider, runtime_id=app_b_id, owned=app_b_owned,
                scope_fingerprint=scope_fingerprint, network_id=network_id,
                deployment_id=candidate_id, image_id=app_b_image_id,
            )
            apps_status = (
                "removed"
                if app_a_cleanup["status"] == "removed" and app_b_cleanup["status"] == "removed"
                else "failed"
            )
            router_cleanup = cleanup_owned_router_container(
                provider, runtime_id=router_id, owned=router_owned,
                scope_fingerprint=scope_fingerprint, network_id=network_id,
                image_id=router_image_id, attempted=router_attempted,
            )
            network_cleanup = cleanup_owned_network(
                provider, network_id=network_id, owned=network_owned,
                scope_fingerprint=scope_fingerprint,
                app_cleanup_status=apps_status,
                router_cleanup_status=router_cleanup["status"],
            )
            image_cleanup = {"status": "removed", "removed": []}
            if (
                apps_status == "removed"
                and router_cleanup["status"] == "removed"
                and network_cleanup["status"] == "removed"
            ):
                for tag, expected_id in ((app_a_tag, app_a_image_id), (app_b_tag, app_b_image_id)):
                    current = _run_docker(
                        provider, ["image", "inspect", "--format", "{{.Id}}", tag]
                    ).strip()
                    if current != expected_id:
                        image_cleanup["status"] = "failed"
                        image_cleanup["detail"] = "smoke image tag no longer resolves to its immutable ID"
                        break
                    _run_docker(provider, ["image", "rm", tag])
                    image_cleanup["removed"].append(tag)
            else:
                image_cleanup = {
                    "status": "preserved",
                    "removed": [],
                    "detail": "images retained because app/Router/network cleanup was not fully verified",
                }
            cleanup_status = (
                "removed"
                if apps_status == "removed"
                and router_cleanup["status"] == "removed"
                and network_cleanup["status"] == "removed"
                and image_cleanup["status"] == "removed"
                else "failed"
            )
            evidence["cleanup"] = {
                "status": cleanup_status,
                "old_app": app_a_cleanup,
                "candidate_app": app_b_cleanup,
                "router": router_cleanup,
                "network": network_cleanup,
                "images": image_cleanup,
            }
            if cleanup_status == "removed":
                shutil.rmtree(temp_root, ignore_errors=True)
            else:
                evidence["status"] = "failed"
                evidence["retained_state_dir"] = str(temp_root)
        else:
            evidence["cleanup"] = {
                "status": "preserved",
                "detail": "replacement did not reach every verified postcondition; all known resources and Host state were retained",
                "router_runtime_id": router_id,
                "network_id": network_id,
                "old_app_runtime_id": app_a_id,
                "candidate_app_runtime_id": app_b_id,
                "state_directory": str(state_root),
                "history_database": str(history_path),
            }
            evidence["retained_state_dir"] = str(temp_root)

    return evidence


def main() -> int:
    evidence = run_live_smoke()
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)
    output_path = os.environ.get("AI_TEAM_ROUTER_REPLACEMENT_EVIDENCE_PATH")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if evidence.get("status") == "ready" and evidence.get("cleanup", {}).get("status") == "removed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
