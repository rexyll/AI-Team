"""Host-owned preparation of an inactive HAProxy slot.

This operation may update only one inactive slot's backend addresses and
administrative readiness. It never changes the active-slot map, never stops an
app, and never retries a Runtime API write. A slot is verified only after
immutable Docker identity checks, fresh app health, per-backend HAProxy
read-back, unchanged active selector, and durable Host server-state snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by Windows CI
    fcntl = None  # type: ignore[assignment]

from runtime.deployment_traffic_router import RouterSlot, TrafficRouteTarget
from runtime.haproxy_runtime_api import (
    HAProxyRuntimeAPIClient,
    get_map_command,
    set_server_address_command,
    set_server_state_command,
    show_maps_command,
    show_servers_state_command,
    show_stat_servers_command,
)
from runtime.haproxy_runtime_readback import (
    ExpectedHAProxyServer,
    HAProxySlotServerObservation,
    parse_get_map_value,
    parse_show_map_registry,
    verify_inactive_slot_readback,
)
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_config import HAPROXY_ACTIVE_SLOT_MAP
from runtime.local_docker_router_container import (
    DockerRouterContainerSpec,
    _verified_state_owner,
    verify_router_container_inspection,
)
from runtime.local_docker_router_container_manager import ROUTER_CONTAINER_INSPECT_FORMAT
from runtime.local_docker_router_network import DockerRouterNetworkRecord
from runtime.local_docker_router_state import (
    LocalDockerRouterStateStore,
    RouterStateRecord,
)
from runtime.local_docker_routed_app import (
    DockerRoutedAppContainerSpec,
    ROUTED_APP_CONTAINER_INSPECT_FORMAT,
    verify_routed_app_inspection,
)

_RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")
_SELECTOR_VALUES = {"none", "slot_a", "slot_b"}

PrepareStatus = Literal[
    "verified", "busy", "unsupported", "unavailable",
    "failed", "mismatch", "invalid_response",
]


@dataclass(frozen=True)
class RouterSlotPrepareResult:
    status: PrepareStatus
    router_runtime_id: str
    app_runtime_id: str
    slot: RouterSlot
    active_selector_before: str | None = None
    active_selector_after: str | None = None
    target: TrafficRouteTarget | None = None
    observations: tuple[HAProxySlotServerObservation, ...] = ()
    state_record: RouterStateRecord | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {
            "verified", "busy", "unsupported", "unavailable",
            "failed", "mismatch", "invalid_response",
        }:
            raise ValueError("invalid Router slot preparation status")
        if not isinstance(self.router_runtime_id, str) or not _RUNTIME_ID.fullmatch(self.router_runtime_id):
            raise ValueError("router_runtime_id must be a full immutable Docker ID")
        if not isinstance(self.app_runtime_id, str) or not _RUNTIME_ID.fullmatch(self.app_runtime_id):
            raise ValueError("app_runtime_id must be a full immutable Docker ID")
        if self.slot not in {"slot_a", "slot_b"}:
            raise ValueError("invalid target slot")
        for value in (self.active_selector_before, self.active_selector_after):
            if value is not None and value not in _SELECTOR_VALUES:
                raise ValueError("invalid active selector observation")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, HAProxySlotServerObservation)
            for item in self.observations
        ):
            raise TypeError("observations must contain HAProxySlotServerObservation values")
        if self.status == "verified":
            if (
                not isinstance(self.target, TrafficRouteTarget)
                or not isinstance(self.state_record, RouterStateRecord)
                or self.active_selector_before != self.active_selector_after
                or self.active_selector_before == self.slot
                or not self.observations
            ):
                raise ValueError("verified slot preparation requires durable read-back and an unchanged different active selector")
        elif self.state_record is not None:
            raise ValueError("unverified slot preparation must not expose a trusted updated state record")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


class _ScopeLockBusy(RuntimeError):
    pass


@contextmanager
def _scope_operation_lock(record: RouterStateRecord) -> Iterator[None]:
    """Serialize slot preparation and future active-switch operations per scope."""
    if fcntl is None or os.name != "posix" or not hasattr(os, "geteuid"):
        raise NotImplementedError("exclusive POSIX Router scope locking is unavailable")
    directory = Path(record.directory)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise OSError("Router scope directory ownership or mode is unsafe")
    lock_path = directory / ".router-operation.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        lock_info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_info.st_mode)
            or lock_info.st_uid != os.geteuid()
            or lock_info.st_nlink != 1
            or stat.S_IMODE(lock_info.st_mode) != 0o600
        ):
            raise OSError("Router scope lock file ownership, type, link count, or mode is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise _ScopeLockBusy("another Host Router operation holds this scope lock") from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


class LocalDockerRouterSlotManager:
    """Prepare and verify an inactive slot without changing active traffic."""

    def __init__(
        self,
        provider: LocalDockerProvider,
        *,
        readback_attempts: int = 12,
        readback_interval_seconds: float = 0.5,
    ) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        if (
            not isinstance(readback_attempts, int)
            or isinstance(readback_attempts, bool)
            or not 1 <= readback_attempts <= 30
        ):
            raise ValueError("readback_attempts must be in the range 1..30")
        if (
            not isinstance(readback_interval_seconds, (int, float))
            or isinstance(readback_interval_seconds, bool)
            or not 0.05 <= readback_interval_seconds <= 2.0
        ):
            raise ValueError("readback_interval_seconds must be in the range 0.05..2.0")
        self.provider = provider
        self.readback_attempts = readback_attempts
        self.readback_interval_seconds = float(readback_interval_seconds)

    def _inspect_payload(
        self, argv: list[str]
    ) -> tuple[Literal["verified", "unavailable", "failed", "invalid_response"], dict | None, str]:
        result, error = self.provider._execute(argv)
        if error:
            status = "unavailable" if self.provider._is_unavailable(error) else "failed"
            return status, None, error
        assert result is not None
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            status = "unavailable" if self.provider._is_unavailable(output) else "failed"
            return status, None, output or "Docker inspect failed"
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return "invalid_response", None, "Docker inspect returned malformed JSON"
        if not isinstance(payload, dict):
            return "invalid_response", None, "Docker inspect must return one JSON object"
        return "verified", payload, ""

    def _verify_host_state(self, state: RouterStateRecord) -> str:
        try:
            _verified_state_owner(state)
        except (OSError, TypeError, ValueError) as exc:
            return f"{type(exc).__name__}: {str(exc)[:400]}"
        expected = (
            (state.config_path, state.config_sha256),
            (state.active_slot_map_path, state.active_slot_map_sha256),
            (state.server_state_path, state.server_state_sha256),
        )
        for raw_path, digest in expected:
            if digest is None:
                return "Host Router state record omitted a required digest"
            path = Path(raw_path)
            try:
                content = path.read_bytes()
            except OSError as exc:
                return f"Host Router state file could not be read: {type(exc).__name__}"
            if hashlib.sha256(content).hexdigest() != digest:
                return f"Host Router state file digest mismatch: {path.name}"
        return ""

    @staticmethod
    def _invalid(
        status: Literal["unavailable", "failed", "mismatch", "invalid_response"],
        router_id: str,
        app_id: str,
        slot: RouterSlot,
        detail: str,
        *,
        active_before: str | None = None,
        active_after: str | None = None,
        observations: tuple[HAProxySlotServerObservation, ...] = (),
    ) -> RouterSlotPrepareResult:
        return RouterSlotPrepareResult(
            status, router_id, app_id, slot,
            active_before, active_after, observations=observations, detail=detail[:1000],
        )

    def prepare_inactive_slot(
        self,
        *,
        router_runtime_id: str,
        router_spec: DockerRouterContainerSpec,
        network: DockerRouterNetworkRecord,
        app_spec: DockerRoutedAppContainerSpec,
        target: TrafficRouteTarget,
        slot: RouterSlot,
        state_record: RouterStateRecord,
    ) -> RouterSlotPrepareResult:
        """Write one inactive server slot once, read it back, then persist state.

        This method intentionally contains no set-map operation. Runtime API
        writes are never retried; only read-only server-health queries are polled.
        """
        if not isinstance(router_runtime_id, str) or not _RUNTIME_ID.fullmatch(router_runtime_id):
            raise ValueError("router_runtime_id must be a full immutable Docker ID")
        if not isinstance(router_spec, DockerRouterContainerSpec):
            raise TypeError("router_spec must be a DockerRouterContainerSpec")
        if not isinstance(network, DockerRouterNetworkRecord):
            raise TypeError("network must be a verified DockerRouterNetworkRecord")
        if not isinstance(app_spec, DockerRoutedAppContainerSpec):
            raise TypeError("app_spec must be a DockerRoutedAppContainerSpec")
        if not isinstance(target, TrafficRouteTarget):
            raise TypeError("target must be a TrafficRouteTarget")
        if not isinstance(state_record, RouterStateRecord):
            raise TypeError("state_record must be a RouterStateRecord")
        if slot not in {"slot_a", "slot_b"}:
            raise ValueError("slot must be slot_a or slot_b")

        router_id = router_runtime_id
        app_id = target.runtime_id
        if (
            router_spec.network_id != network.network_id
            or router_spec.network_name != network.network_name
            or router_spec.scope_fingerprint != network.scope_fingerprint
            or app_spec.network_id != network.network_id
            or app_spec.network_name != network.network_name
            or app_spec.scope_fingerprint != network.scope_fingerprint
            or app_spec.port_bindings != router_spec.port_bindings
            or target.port_bindings != router_spec.port_bindings
            or target.deployment_id != app_spec.deployment_id
            or state_record.network_name != network.network_name
            or state_record.scope_fingerprint != network.scope_fingerprint
            or Path(state_record.directory) != Path(router_spec.state_directory)
        ):
            return self._invalid(
                "mismatch", router_id, app_id, slot,
                "Router, app, network, port bindings, or Host state scope identities do not match",
            )

        if fcntl is None or os.name != "posix":
            return self._invalid(
                "unavailable", router_id, app_id, slot,
                "Host Router slot preparation requires POSIX scope locking",
            )

        try:
            lock_context = _scope_operation_lock(state_record)
            with lock_context:
                return self._prepare_locked(
                    router_id, router_spec, network, app_spec, target,
                    slot, state_record,
                )
        except _ScopeLockBusy as exc:
            return RouterSlotPrepareResult(
                "busy", router_id, app_id, slot, detail=str(exc)
            )
        except NotImplementedError as exc:
            return self._invalid("unavailable", router_id, app_id, slot, str(exc))
        except (OSError, ValueError) as exc:
            return self._invalid("failed", router_id, app_id, slot, f"{type(exc).__name__}: {exc}")

    def _prepare_locked(
        self,
        router_id: str,
        router_spec: DockerRouterContainerSpec,
        network: DockerRouterNetworkRecord,
        app_spec: DockerRoutedAppContainerSpec,
        target: TrafficRouteTarget,
        slot: RouterSlot,
        state_record: RouterStateRecord,
    ) -> RouterSlotPrepareResult:
        app_id = target.runtime_id
        state_error = self._verify_host_state(state_record)
        if state_error:
            return self._invalid("mismatch", router_id, app_id, slot, state_error)

        router_status, router_payload, router_detail = self._inspect_payload([
            "container", "inspect", "--format",
            ROUTER_CONTAINER_INSPECT_FORMAT,
            router_id,
        ])
        if router_status != "verified" or router_payload is None:
            return self._invalid(router_status, router_id, app_id, slot, router_detail)
        router_verification = verify_router_container_inspection(router_payload, router_spec)
        if router_verification.status != "verified" or router_verification.container_id != router_id:
            return self._invalid(
                "mismatch", router_id, app_id, slot,
                router_verification.detail or "Router immutable runtime ID mismatch",
            )

        app_status, app_payload, app_detail = self._inspect_payload([
            "container", "inspect", "--format",
            ROUTED_APP_CONTAINER_INSPECT_FORMAT,
            app_id,
        ])
        if app_status != "verified" or app_payload is None:
            return self._invalid(app_status, router_id, app_id, slot, app_detail)
        app_verification = verify_routed_app_inspection(app_payload, app_spec)
        if (
            app_verification.status != "verified"
            or app_verification.target != target
            or not app_verification.route_eligible
        ):
            return self._invalid(
                "mismatch", router_id, app_id, slot,
                app_verification.health_detail or "Routed app is not freshly healthy and route eligible",
            )

        client = HAProxyRuntimeAPIClient(self.provider, router_id)
        registry = client.execute(show_maps_command())
        if registry.status != "succeeded":
            return self._invalid(registry.status, router_id, app_id, slot, registry.detail)
        try:
            map_id = parse_show_map_registry(
                registry.response, expected_path=HAPROXY_ACTIVE_SLOT_MAP
            )
        except ValueError as exc:
            return self._invalid("invalid_response", router_id, app_id, slot, str(exc))
        active_result = client.execute(get_map_command(map_id, "active"))
        if active_result.status != "succeeded":
            return self._invalid(active_result.status, router_id, app_id, slot, active_result.detail)
        try:
            active_before = parse_get_map_value(
                active_result.response, expected_key="active"
            )
        except ValueError as exc:
            return self._invalid("invalid_response", router_id, app_id, slot, str(exc))
        if active_before == slot:
            return self._invalid(
                "mismatch", router_id, app_id, slot,
                "Requested slot is currently active and cannot be prepared as inactive",
                active_before=active_before,
            )

        # Writes are each sent at most once. Any ambiguous write response stops
        # the mutation sequence; read-back below may prove the resulting state.
        write_error = ""
        for binding in router_spec.port_bindings:
            backend = f"be_p{binding.host_port}"
            address_result = client.execute(
                set_server_address_command(backend, slot, target.address, binding.container_port)
            )
            if address_result.status != "succeeded":
                write_error = address_result.detail or f"set address failed for {backend}/{slot}"
                break
            ready_result = client.execute(set_server_state_command(backend, slot, "ready"))
            if ready_result.status != "succeeded":
                write_error = ready_result.detail or f"set ready failed for {backend}/{slot}"
                break

        observations: list[HAProxySlotServerObservation] = []
        last_mismatch = ""
        readback_verified = False
        for attempt in range(self.readback_attempts):
            observations = []
            last_mismatch = ""
            for binding in router_spec.port_bindings:
                backend = f"be_p{binding.host_port}"
                state_result = client.execute(show_servers_state_command(backend))
                stat_result = client.execute(show_stat_servers_command(backend))
                if state_result.status != "succeeded" or stat_result.status != "succeeded":
                    detail = state_result.detail if state_result.status != "succeeded" else stat_result.detail
                    status = (
                        "unavailable"
                        if "unavailable" in {state_result.status, stat_result.status}
                        else "failed"
                    )
                    return self._invalid(status, router_id, app_id, slot, detail or f"Read-back failed for {backend}")
                expected = (
                    ExpectedHAProxyServer(backend, slot, target.address, binding.container_port),
                )
                readback = verify_inactive_slot_readback(
                    expected,
                    servers_state_response=state_result.response,
                    stat_response=stat_result.response,
                )
                if readback.status == "invalid_response":
                    return self._invalid(
                        "invalid_response", router_id, app_id, slot, readback.detail,
                        active_before=active_before, observations=tuple(observations),
                    )
                if readback.status != "verified":
                    last_mismatch = readback.detail
                    break
                observations.extend(readback.observations)
            if not last_mismatch:
                readback_verified = True
                break
            if attempt + 1 < self.readback_attempts:
                time.sleep(self.readback_interval_seconds)

        if not readback_verified:
            detail = last_mismatch or write_error or "Inactive slot did not become healthy before the read-back deadline"
            return self._invalid(
                "mismatch", router_id, app_id, slot, detail,
                active_before=active_before, observations=tuple(observations),
            )

        # Confirm that no concurrent actor changed the active selector while
        # the inactive slot was being prepared.
        final_selector = client.execute(get_map_command(map_id, "active"))
        if final_selector.status != "succeeded":
            return self._invalid(
                final_selector.status, router_id, app_id, slot, final_selector.detail,
                active_before=active_before, observations=tuple(observations),
            )
        try:
            active_after = parse_get_map_value(
                final_selector.response,
                expected_key="active",
                expected_value=active_before,
            )
        except ValueError as exc:
            return self._invalid(
                "mismatch", router_id, app_id, slot, str(exc),
                active_before=active_before, observations=tuple(observations),
            )

        full_state = client.execute(show_servers_state_command())
        if full_state.status != "succeeded":
            return self._invalid(
                full_state.status, router_id, app_id, slot, full_state.detail,
                active_before=active_before, active_after=active_after,
                observations=tuple(observations),
            )
        state_store = LocalDockerRouterStateStore(str(Path(state_record.directory).parent))
        persisted = state_store.persist_servers_state(
            state_record, router_spec.port_bindings, full_state.response
        )
        if persisted.status != "persisted" or persisted.record is None:
            return self._invalid(
                "failed", router_id, app_id, slot,
                persisted.detail or "Host server-state snapshot could not be persisted",
                active_before=active_before, active_after=active_after,
                observations=tuple(observations),
            )

        # Reconfirm the Router/app identities and the unchanged selector after
        # Host persistence. No active-map write is performed in this method.
        router_after_status, router_after_payload, router_after_detail = self._inspect_payload([
            "container", "inspect", "--format",
            __import__("runtime.local_docker_router_container_manager", fromlist=["ROUTER_CONTAINER_INSPECT_FORMAT"]).ROUTER_CONTAINER_INSPECT_FORMAT,
            router_id,
        ])
        app_after_status, app_after_payload, app_after_detail = self._inspect_payload([
            "container", "inspect", "--format",
            ROUTED_APP_CONTAINER_INSPECT_FORMAT,
            app_id,
        ])
        if router_after_status != "verified" or router_after_payload is None:
            return self._invalid(router_after_status, router_id, app_id, slot, router_after_detail)
        if app_after_status != "verified" or app_after_payload is None:
            return self._invalid(app_after_status, router_id, app_id, slot, app_after_detail)
        router_after_verification = verify_router_container_inspection(
            router_after_payload, router_spec
        )
        app_after_verification = verify_routed_app_inspection(
            app_after_payload, app_spec
        )
        if (
            router_after_verification.status != "verified"
            or router_after_verification.container_id != router_id
            or app_after_verification.status != "verified"
            or app_after_verification.target != target
            or not app_after_verification.route_eligible
        ):
            return self._invalid(
                "mismatch", router_id, app_id, slot,
                "Router or routed app immutable identity, endpoint, or health changed during slot preparation",
                active_before=active_before, active_after=active_after,
                observations=tuple(observations),
            )
        return RouterSlotPrepareResult(
            "verified",
            router_id,
            app_id,
            slot,
            active_before,
            active_after,
            target,
            tuple(observations),
            persisted.record,
        )
