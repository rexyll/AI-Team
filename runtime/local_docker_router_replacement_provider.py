"""Provider adapter joining Local Docker Router slots to durable replacement.

The adapter is intentionally fail-closed: the generic replacement coordinator
owns its journal and active deployment CAS; this provider owns Router/app
identity, slot preparation, active-map read-back, connection drain and
inspect-confirmed container retirement. No automatic reconciliation is exposed.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import (
    DeploymentArtifact,
    DeploymentOperationResult,
    DeploymentRecord,
    DeploymentRequest,
    HealthCheckResult,
)
from runtime.deployment_traffic_router import (
    RouterSlot,
    TrafficRouteTarget,
    TrafficRouterScope,
)
from runtime.haproxy_runtime_api import (
    HAProxyRuntimeAPIClient,
    get_map_command,
    show_maps_command,
)
from runtime.haproxy_runtime_readback import parse_get_map_value, parse_show_map_registry
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_routed_app import (
    LocalDockerRoutedAppManager,
    build_routed_app_container_spec,
)
from runtime.local_docker_router_config import HAPROXY_ACTIVE_SLOT_MAP
from runtime.local_docker_router_host import LocalDockerRouterHostManager, LocalDockerRouterHostResult
from runtime.local_docker_router_slot_manager import (
    LocalDockerRouterSlotManager,
    RouterSlotPrepareResult,
    RouterSlotSwitchResult,
)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LocalDockerRouterReplacementProvider:
    """Replacement capability for one durable Local Docker Router scope."""

    name = "docker-local"

    def __init__(
        self,
        provider: LocalDockerProvider,
        history: DeploymentHistoryStore,
        router_host: LocalDockerRouterHostManager,
        app_manager: LocalDockerRoutedAppManager,
        slot_manager: LocalDockerRouterSlotManager,
        scope: TrafficRouterScope,
        port_bindings,
    ) -> None:
        if not all(callable(getattr(provider, name, None)) for name in ("_execute", "inspect_runtime")):
            raise TypeError("provider must expose Host Docker execution and immutable runtime inspection")
        if not isinstance(history, DeploymentHistoryStore):
            raise TypeError("history must be a DeploymentHistoryStore")
        if not callable(getattr(router_host, "ensure_router", None)):
            raise TypeError("router_host must expose ensure_router")
        if not callable(getattr(app_manager, "ensure_app", None)) or not callable(getattr(app_manager, "_inspect", None)):
            raise TypeError("app_manager must expose ensure_app and inspect")
        if not all(callable(getattr(slot_manager, name, None)) for name in (
            "prepare_inactive_slot", "switch_active_slot", "drain_inactive_slot"
        )):
            raise TypeError("slot_manager must expose prepare, switch and drain operations")
        if not isinstance(scope, TrafficRouterScope) or scope.provider != "docker-local":
            raise ValueError("scope must be a docker-local TrafficRouterScope")
        if not isinstance(port_bindings, tuple) or not port_bindings:
            raise ValueError("port_bindings must be a non-empty tuple")
        if getattr(router_host, "provider", None) is not provider or getattr(router_host, "history", None) is not history:
            raise ValueError("Router Host manager must share the exact provider and history instances")
        if getattr(app_manager, "provider", None) is not provider or getattr(slot_manager, "provider", None) is not provider:
            raise ValueError("app and slot managers must share the exact LocalDockerProvider instance")
        self.provider = provider
        self.history = history
        self.router_host = router_host
        self.app_manager = app_manager
        self.slot_manager = slot_manager
        self.scope = scope
        self.port_bindings = router_host._validate_bindings(port_bindings)
        self._operations: dict[str, dict[str, object]] = {}

    def _host(self) -> LocalDockerRouterHostResult:
        return self.router_host.ensure_router(self.scope, self.port_bindings)

    @staticmethod
    def _slot_for_target(record, runtime_id: str) -> RouterSlot | None:
        for slot, target in record.slot_targets:
            if target.runtime_id == runtime_id:
                return slot
        return None

    def health_check(self, record: DeploymentRecord) -> HealthCheckResult:
        if record.provider != self.name or record.container_id is None:
            return HealthCheckResult("unavailable", _now(), "docker immutable inspect", "Deployment record has no routed app identity")
        inspection = self.provider.inspect_runtime(record)
        if inspection.status != "verified" or inspection.observed_runtime_id != record.container_id:
            return HealthCheckResult(
                "unavailable", _now(), "docker immutable inspect",
                inspection.detail or "Routed app immutable identity could not be verified",
            )
        return HealthCheckResult(
            inspection.health_status, inspection.checked_at, inspection.probe, inspection.detail
        )

    def immutable_runtime_id(self, record: DeploymentRecord) -> str | None:
        if record.provider != self.name:
            return None
        return record.container_id

    def prepare_candidate(
        self,
        request: DeploymentRequest,
        target: DeploymentRecord,
        previous: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult:
        host = self._host()
        if host.status not in {"ready", "created"} or host.router_record is None or host.state_record is None or host.network is None or host.container_spec is None:
            return DeploymentOperationResult(
                "prepare_candidate", "unavailable" if host.status in {"unavailable", "unsupported"} else "failed",
                self.name, host.detail or "Router Host scope is not verified",
            )
        router = host.router_record
        if router.active_slot not in {"slot_a", "slot_b"} or router.active_target is None:
            return DeploymentOperationResult(
                "prepare_candidate", "unsupported", self.name,
                "Replacement requires an already active, registry-backed Router slot",
            )
        if (
            router.active_target.runtime_id != previous.container_id
            or router.active_target.deployment_id != previous.deployment_id
            or router.active_slot != self._slot_for_target(router, previous.container_id or "")
        ):
            return DeploymentOperationResult(
                "prepare_candidate", "failed", self.name,
                "Active Router target does not match the Host active deployment record",
            )
        slot: RouterSlot = "slot_b" if router.active_slot == "slot_a" else "slot_a"
        if target.artifact.provider != self.name:
            return DeploymentOperationResult("prepare_candidate", "failed", self.name, "Candidate artifact provider mismatch")
        self._operations[operation_id] = {
            "router": router,
            "state": host.state_record,
            "network": host.network,
            "router_spec": host.container_spec,
            "slot": slot,
            "previous_slot": router.active_slot,
            "previous_target": router.active_target,
            "target": target,
            "request": request,
        }
        return DeploymentOperationResult("prepare_candidate", "succeeded", self.name, "Router scope and inactive slot reserved")

    def start_candidate(
        self,
        request: DeploymentRequest,
        target: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult:
        context = self._operations.get(operation_id)
        if context is None or context.get("target") != target or context.get("request") != request:
            return DeploymentOperationResult("start_candidate", "failed", self.name, "No matching prepared Router replacement context")
        network = context["network"]
        slot = context["slot"]
        router = context["router"]
        state = context["state"]
        router_spec = context["router_spec"]
        app_spec = build_routed_app_container_spec(
            network, target.artifact, target.deployment_id, self.port_bindings
        )
        ensured = self.app_manager.ensure_app(app_spec, target.artifact)
        if not ensured.route_eligible or ensured.target is None:
            status = "unavailable" if ensured.status == "unavailable" or ensured.health_status == "unavailable" else "failed"
            return DeploymentOperationResult(
                "start_candidate", status, self.name,
                ensured.detail or ensured.health_detail or "Candidate routed app is not healthy and route eligible",
            )
        prepared = self.slot_manager.prepare_inactive_slot(
            router_runtime_id=router.router_runtime_id,
            router_spec=router_spec,
            network=network,
            app_spec=app_spec,
            target=ensured.target,
            slot=slot,
            state_record=state,
        )
        if prepared.status != "verified" or prepared.state_record is None:
            status = "unavailable" if prepared.status in {"unavailable", "busy"} else "failed"
            return DeploymentOperationResult(
                "start_candidate", status, self.name,
                prepared.detail or "Candidate inactive slot preparation was not verified",
            )
        updated_slots = tuple(
            (existing_slot, existing_target)
            for existing_slot, existing_target in router.slot_targets
            if existing_slot != slot
        ) + ((slot, ensured.target),)
        updated_router = replace(
            router,
            slot_targets=updated_slots,
            route_generation=uuid4().hex,
        )
        try:
            persisted = self.history.update_traffic_router(
                updated_router,
                prepared.state_record,
                expected_generation=router.route_generation,
                expected_state_map_sha256=state.active_slot_map_sha256,
            )
        except Exception as exc:
            return DeploymentOperationResult(
                "start_candidate", "failed", self.name,
                f"Candidate slot was prepared but registry commit failed: {type(exc).__name__}",
            )
        candidate = replace(
            target,
            status="running",
            health_status="healthy",
            container_id=ensured.target.runtime_id,
            endpoint=f"tcp://127.0.0.1:{self.port_bindings[0].host_port}",
        )
        context.update({
            "router": persisted,
            "state": prepared.state_record,
            "app_spec": app_spec,
            "target_route": ensured.target,
            "candidate": candidate,
        })
        return DeploymentOperationResult(
            "start_candidate", "succeeded", self.name,
            "Candidate app started, health verified, inactive slot prepared and registry committed",
            artifact=target.artifact, record=candidate,
        )

    def verify_candidate(self, candidate: DeploymentRecord) -> HealthCheckResult:
        for context in self._operations.values():
            if context.get("candidate") == candidate:
                app_spec = context.get("app_spec")
                if app_spec is None:
                    break
                status, verification, detail = self.app_manager._inspect(app_spec)
                if status != "verified" or verification is None or not verification.route_eligible or verification.target is None or verification.target.runtime_id != candidate.container_id:
                    return HealthCheckResult("unhealthy", _now(), "routed app inspect/health", detail or "Candidate immutable app/health read-back failed")
                return HealthCheckResult("healthy", _now(), "routed app inspect/health")
        return HealthCheckResult("unavailable", _now(), "routed app inspect/health", "Candidate has no in-memory prepared operation context")

    def switch_traffic(
        self,
        candidate: DeploymentRecord,
        previous: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult:
        context = self._operations.get(operation_id)
        if context is None or context.get("candidate") != candidate:
            return DeploymentOperationResult("switch_traffic", "failed", self.name, "No verified candidate context")
        slot = context["slot"]
        router = context["router"]
        result = self.slot_manager.switch_active_slot(
            router_runtime_id=router.router_runtime_id,
            router_spec=context["router_spec"],
            network=context["network"],
            app_spec=context["app_spec"],
            target=context["target_route"],
            slot=slot,
            expected_active_slot=context["previous_slot"],
            state_record=context["state"],
        )
        if result.status != "verified" or result.state_record is None:
            status = "unavailable" if result.status in {"unavailable", "busy"} else "failed"
            return DeploymentOperationResult(
                "switch_traffic", status, self.name,
                result.detail or "Router active-slot switch was not verified",
            )
        updated_router = replace(
            router,
            active_slot=slot,
            active_target=context["target_route"],
            route_generation=uuid4().hex,
        )
        try:
            persisted = self.history.update_traffic_router(
                updated_router,
                result.state_record,
                expected_generation=router.route_generation,
                expected_state_map_sha256=context["state"].active_slot_map_sha256,
            )
        except Exception as exc:
            return DeploymentOperationResult(
                "switch_traffic", "failed", self.name,
                f"Router switched but registry commit failed: {type(exc).__name__}",
            )
        context.update({"router": persisted, "state": result.state_record})
        return DeploymentOperationResult(
            "switch_traffic", "succeeded", self.name,
            "Router selector and Host registry active target verified",
        )

    def read_traffic_target(self, request: DeploymentRequest) -> str | None:
        if request.project != self.scope.project or request.environment != self.scope.environment:
            return None
        host = self._host()
        if host.status != "ready" or host.router_record is None or host.container_spec is None:
            return None
        router = host.router_record
        client = HAProxyRuntimeAPIClient(self.provider, router.router_runtime_id)
        maps = client.execute(show_maps_command())
        if maps.status != "succeeded":
            return None
        try:
            map_id = parse_show_map_registry(maps.response, expected_path=HAPROXY_ACTIVE_SLOT_MAP)
        except ValueError:
            return None
        selector = client.execute(get_map_command(map_id, "active"))
        if selector.status != "succeeded":
            return None
        try:
            active = parse_get_map_value(selector.response, expected_key="active")
        except ValueError:
            return None
        if active == "none":
            return None
        if router.active_slot != active:
            return None
        target = dict(router.slot_targets).get(active)
        return target.runtime_id if target is not None else None

    def retire_previous(
        self,
        previous: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult:
        context = self._operations.get(operation_id)
        if context is None or context.get("previous_target") is None:
            return DeploymentOperationResult("retire_previous", "failed", self.name, "No previous Router slot context")
        router = context["router"]
        old_slot = context["previous_slot"]
        active_slot = context["slot"]
        if old_slot == active_slot or previous.container_id != context["previous_target"].runtime_id:
            return DeploymentOperationResult("retire_previous", "failed", self.name, "Previous runtime/slot identity mismatch")
        drained = self.slot_manager.drain_inactive_slot(
            router_runtime_id=router.router_runtime_id,
            router_spec=context["router_spec"],
            network=context["network"],
            slot=old_slot,
            expected_active_slot=active_slot,
            state_record=context["state"],
        )
        if drained.status != "verified" or drained.state_record is None:
            status = "unavailable" if drained.status in {"unavailable", "busy"} else "failed"
            return DeploymentOperationResult(
                "retire_previous", status, self.name,
                drained.detail or "Previous slot was not confirmed drained",
            )
        stopped = self._stop_by_immutable_id(previous)
        if stopped.status != "succeeded" or stopped.record is None:
            return stopped
        # Remove the retired slot from the durable slot inventory only after
        # HAProxy reported MAINT + zero sessions and Docker inspect confirmed
        # the exact previous immutable container is stopped.
        updated_router = replace(
            router,
            slot_targets=tuple((s, t) for s, t in router.slot_targets if s != old_slot),
            route_generation=uuid4().hex,
        )
        try:
            self.history.update_traffic_router(
                updated_router,
                drained.state_record,
                expected_generation=router.route_generation,
                expected_state_map_sha256=context["state"].active_slot_map_sha256,
            )
        except Exception as exc:
            return DeploymentOperationResult(
                "retire_previous", "failed", self.name,
                f"Previous runtime stopped but Router registry retirement commit failed: {type(exc).__name__}",
            )
        context.update({"router": updated_router, "state": drained.state_record})
        return stopped

    def abort_candidate(
        self,
        candidate: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult:
        context = self._operations.get(operation_id)
        if context is None or context.get("candidate") != candidate:
            return DeploymentOperationResult("abort_candidate", "failed", self.name, "No candidate Router context")
        router = context["router"]
        slot = context["slot"]
        active_slot = context["previous_slot"]
        drained = self.slot_manager.drain_inactive_slot(
            router_runtime_id=router.router_runtime_id,
            router_spec=context["router_spec"],
            network=context["network"],
            slot=slot,
            expected_active_slot=active_slot,
            state_record=context["state"],
        )
        if drained.status != "verified" or drained.state_record is None:
            return DeploymentOperationResult("abort_candidate", "failed", self.name, drained.detail or "Candidate slot is not safely drained")
        stopped = self._stop_by_immutable_id(candidate)
        if stopped.status != "succeeded":
            return stopped
        updated_router = replace(
            router,
            slot_targets=tuple((s, t) for s, t in router.slot_targets if s != slot),
            route_generation=uuid4().hex,
        )
        try:
            self.history.update_traffic_router(
                updated_router,
                drained.state_record,
                expected_generation=router.route_generation,
                expected_state_map_sha256=context["state"].active_slot_map_sha256,
            )
        except Exception as exc:
            return DeploymentOperationResult(
                "abort_candidate", "failed", self.name,
                f"Candidate stopped but Router registry cleanup commit failed: {type(exc).__name__}",
            )
        return stopped

    def _stop_by_immutable_id(self, record: DeploymentRecord) -> DeploymentOperationResult:
        if record.provider != self.name or record.container_id is None:
            return DeploymentOperationResult("stop", "failed", self.name, "Record has no docker-local immutable container ID")
        before = self.provider.inspect_runtime(record)
        if before.status != "verified" or before.observed_runtime_id != record.container_id or before.runtime_state != "running":
            return DeploymentOperationResult("stop", "failed", self.name, "Container is not the expected running immutable runtime")
        result, error = self.provider._execute(["stop", "--time", "10", record.container_id])
        if error or result is None or result.returncode != 0:
            return DeploymentOperationResult("stop", "failed", self.name, error or (result.stderr if result else "Docker stop returned no result"))
        after = self.provider.inspect_runtime(record)
        if after.status != "verified" or after.observed_runtime_id != record.container_id or after.runtime_state not in {"exited", "dead"}:
            return DeploymentOperationResult("stop", "failed", self.name, after.detail or "Docker did not confirm the exact container stopped")
        stopped_record = replace(record, status="stopped", health_status="unhealthy")
        return DeploymentOperationResult(
            "stop", "succeeded", self.name,
            "Container stop confirmed by immutable-ID inspect",
            artifact=record.artifact, record=stopped_record,
        )
