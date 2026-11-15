"""Provider-neutral contracts for host-owned Docker traffic routing.

The module is data-only. It does not create networks, invoke Docker/HAProxy,
change active routes, or authorize deployment reconciliation.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal, Protocol

RouterSlot = Literal["slot_a", "slot_b"]
TrafficProtocol = Literal["tcp"]
TrafficBackendState = Literal["up", "down", "unknown"]
RouterOperationStatus = Literal["succeeded", "failed", "unavailable", "unsupported"]
RouterOperation = Literal[
    "ensure_router",
    "inspect_router",
    "prepare_slot",
    "switch_active_slot",
    "drain_slot",
]
RouteReadbackStatus = Literal[
    "verified",
    "mismatch",
    "unavailable",
    "invalid_response",
]
SlotDrainState = Literal["ready", "drain", "maint", "unknown"]

_RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")


def _non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _runtime_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _RUNTIME_ID.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase immutable runtime ID")


@dataclass(frozen=True)
class TrafficRouterScope:
    """Uniquely identifies one router/network/host-port ownership scope."""

    provider: str
    project: str
    environment: str

    def __post_init__(self) -> None:
        for name in ("provider", "project", "environment"):
            _non_empty(getattr(self, name), name)


@dataclass(frozen=True)
class TrafficPortBinding:
    """One externally stable host TCP port and its app-container destination."""

    host_port: int
    container_port: int
    protocol: TrafficProtocol = "tcp"

    def __post_init__(self) -> None:
        for name in ("host_port", "container_port"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
                raise ValueError(f"{name} must be an integer in the range 1..65535")
        if self.protocol != "tcp":
            raise ValueError("only TCP traffic routing is supported by the initial router")


@dataclass(frozen=True)
class TrafficRouteTarget:
    """Host-verified app runtime identity and its private-network endpoint."""

    deployment_id: str
    runtime_id: str
    address: str
    port_bindings: tuple[TrafficPortBinding, ...]

    def __post_init__(self) -> None:
        _non_empty(self.deployment_id, "deployment_id")
        _runtime_id(self.runtime_id, "runtime_id")
        _non_empty(self.address, "address")
        try:
            ipaddress.ip_address(self.address)
        except ValueError as exc:
            raise ValueError("address must be a literal IPv4 or IPv6 address") from exc
        if not isinstance(self.port_bindings, tuple) or not self.port_bindings:
            raise ValueError("port_bindings must be a non-empty tuple")
        if any(not isinstance(item, TrafficPortBinding) for item in self.port_bindings):
            raise TypeError("port_bindings must contain TrafficPortBinding values")
        host_ports = [item.host_port for item in self.port_bindings]
        if len(host_ports) != len(set(host_ports)):
            raise ValueError("host ports must be unique within a route target")


@dataclass(frozen=True)
class TrafficRouterRecord:
    """Durable Host identity for the per-scope HAProxy router."""

    scope: TrafficRouterScope
    router_deployment_id: str
    router_runtime_id: str
    network_name: str
    port_bindings: tuple[TrafficPortBinding, ...]
    active_slot: RouterSlot | None
    active_target: TrafficRouteTarget | None
    route_generation: str
    created_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, TrafficRouterScope):
            raise TypeError("scope must be a TrafficRouterScope")
        _non_empty(self.router_deployment_id, "router_deployment_id")
        _runtime_id(self.router_runtime_id, "router_runtime_id")
        _non_empty(self.network_name, "network_name")
        _non_empty(self.route_generation, "route_generation")
        _non_empty(self.created_at, "created_at")
        if not isinstance(self.port_bindings, tuple) or not self.port_bindings:
            raise ValueError("port_bindings must be a non-empty tuple")
        if any(not isinstance(item, TrafficPortBinding) for item in self.port_bindings):
            raise TypeError("port_bindings must contain TrafficPortBinding values")
        host_ports = [item.host_port for item in self.port_bindings]
        if len(host_ports) != len(set(host_ports)):
            raise ValueError("router host ports must be unique")
        if self.active_slot not in {None, "slot_a", "slot_b"}:
            raise ValueError("invalid active_slot")
        if (self.active_slot is None) != (self.active_target is None):
            raise ValueError("active_slot and active_target must both be set or both be absent")
        if self.active_target is not None:
            if not isinstance(self.active_target, TrafficRouteTarget):
                raise TypeError("active_target must be a TrafficRouteTarget")
            if self.active_target.port_bindings != self.port_bindings:
                raise ValueError("active target port bindings must match router scope bindings")


@dataclass(frozen=True)
class TrafficPortObservation:
    """Read-back for one Router frontend/backend mapping."""

    host_port: int
    protocol: TrafficProtocol
    slot: RouterSlot | None
    deployment_id: str | None
    runtime_id: str | None
    address: str | None
    container_port: int | None
    backend_state: TrafficBackendState
    active_connections: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.host_port, int) or isinstance(self.host_port, bool) or not 1 <= self.host_port <= 65535:
            raise ValueError("host_port must be an integer in the range 1..65535")
        if self.protocol != "tcp":
            raise ValueError("only TCP port observations are supported")
        if self.slot not in {None, "slot_a", "slot_b"}:
            raise ValueError("invalid observed slot")
        if self.deployment_id is not None:
            _non_empty(self.deployment_id, "deployment_id")
        if self.runtime_id is not None:
            _runtime_id(self.runtime_id, "runtime_id")
        if self.address is not None:
            try:
                ipaddress.ip_address(self.address)
            except ValueError as exc:
                raise ValueError("observed address must be a literal IP address") from exc
        if self.container_port is not None and (
            not isinstance(self.container_port, int)
            or isinstance(self.container_port, bool)
            or not 1 <= self.container_port <= 65535
        ):
            raise ValueError("container_port must be an integer in the range 1..65535")
        if self.backend_state not in {"up", "down", "unknown"}:
            raise ValueError("invalid backend_state")
        if self.active_connections is not None and (
            not isinstance(self.active_connections, int)
            or isinstance(self.active_connections, bool)
            or self.active_connections < 0
        ):
            raise ValueError("active_connections must be a non-negative integer when provided")


@dataclass(frozen=True)
class TrafficRouteReadback:
    """Router-observed active route, checked against an expected journal target."""

    scope: TrafficRouterScope
    status: RouteReadbackStatus
    expected_router_runtime_id: str
    observed_router_runtime_id: str | None
    expected_generation: str
    observed_generation: str | None
    expected_slot: RouterSlot
    observed_slot: RouterSlot | None
    expected_target: TrafficRouteTarget
    observed_target_runtime_id: str | None
    observed_target_address: str | None
    port_observations: tuple[TrafficPortObservation, ...]
    checked_at: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scope, TrafficRouterScope):
            raise TypeError("scope must be a TrafficRouterScope")
        if self.status not in {"verified", "mismatch", "unavailable", "invalid_response"}:
            raise ValueError("invalid route read-back status")
        _runtime_id(self.expected_router_runtime_id, "expected_router_runtime_id")
        if self.observed_router_runtime_id is not None:
            _runtime_id(self.observed_router_runtime_id, "observed_router_runtime_id")
        _non_empty(self.expected_generation, "expected_generation")
        if self.observed_generation is not None:
            _non_empty(self.observed_generation, "observed_generation")
        if self.expected_slot not in {"slot_a", "slot_b"}:
            raise ValueError("invalid expected_slot")
        if self.observed_slot not in {None, "slot_a", "slot_b"}:
            raise ValueError("invalid observed_slot")
        if not isinstance(self.expected_target, TrafficRouteTarget):
            raise TypeError("expected_target must be a TrafficRouteTarget")
        if self.observed_target_runtime_id is not None:
            _runtime_id(self.observed_target_runtime_id, "observed_target_runtime_id")
        if self.observed_target_address is not None:
            try:
                ipaddress.ip_address(self.observed_target_address)
            except ValueError as exc:
                raise ValueError("observed_target_address must be a literal IP address") from exc
        if not isinstance(self.port_observations, tuple) or any(
            not isinstance(item, TrafficPortObservation) for item in self.port_observations
        ):
            raise TypeError("port_observations must be a tuple of TrafficPortObservation")
        _non_empty(self.checked_at, "checked_at")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")

        if self.status == "verified":
            if (
                self.observed_router_runtime_id != self.expected_router_runtime_id
                or self.observed_generation != self.expected_generation
                or self.observed_slot != self.expected_slot
                or self.observed_target_runtime_id != self.expected_target.runtime_id
                or self.observed_target_address != self.expected_target.address
            ):
                raise ValueError("verified route read-back must match router, generation, slot and target")
            by_port = {item.host_port: item for item in self.port_observations}
            expected_ports = {item.host_port: item for item in self.expected_target.port_bindings}
            if len(by_port) != len(self.port_observations) or set(by_port) != set(expected_ports):
                raise ValueError("verified route read-back must contain exactly one observation per host port")
            for host_port, expected in expected_ports.items():
                observed = by_port[host_port]
                if (
                    observed.protocol != expected.protocol
                    or observed.slot != self.expected_slot
                    or observed.deployment_id != self.expected_target.deployment_id
                    or observed.runtime_id != self.expected_target.runtime_id
                    or observed.address != self.expected_target.address
                    or observed.container_port != expected.container_port
                    or observed.backend_state != "up"
                ):
                    raise ValueError("verified route read-back contains a mismatched or unhealthy backend")


@dataclass(frozen=True)
class TrafficSlotConnectionSnapshot:
    """Read-only connection/drain state for one Router slot."""

    router_runtime_id: str
    slot: RouterSlot
    status: Literal["verified", "unavailable", "invalid_response"]
    drain_state: SlotDrainState
    active_connections: int | None
    checked_at: str
    detail: str = ""

    def __post_init__(self) -> None:
        _runtime_id(self.router_runtime_id, "router_runtime_id")
        if self.slot not in {"slot_a", "slot_b"}:
            raise ValueError("invalid slot")
        if self.status not in {"verified", "unavailable", "invalid_response"}:
            raise ValueError("invalid connection snapshot status")
        if self.drain_state not in {"ready", "drain", "maint", "unknown"}:
            raise ValueError("invalid drain_state")
        if self.active_connections is not None and (
            not isinstance(self.active_connections, int)
            or isinstance(self.active_connections, bool)
            or self.active_connections < 0
        ):
            raise ValueError("active_connections must be a non-negative integer when provided")
        if self.status == "verified" and (
            self.active_connections is None or self.drain_state == "unknown"
        ):
            raise ValueError("verified connection snapshot needs a known drain state and count")
        _non_empty(self.checked_at, "checked_at")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


@dataclass(frozen=True)
class TrafficRouterOperationResult:
    """Bounded result for one idempotent Host-owned Router operation."""

    operation_id: str
    operation: RouterOperation
    status: RouterOperationStatus
    router_runtime_id: str | None = None
    route_generation: str | None = None
    active_slot: RouterSlot | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        _non_empty(self.operation_id, "operation_id")
        if self.operation not in {
            "ensure_router", "inspect_router", "prepare_slot",
            "switch_active_slot", "drain_slot",
        }:
            raise ValueError("unsupported router operation")
        if self.status not in {"succeeded", "failed", "unavailable", "unsupported"}:
            raise ValueError("invalid router operation status")
        if self.router_runtime_id is not None:
            _runtime_id(self.router_runtime_id, "router_runtime_id")
        if self.route_generation is not None:
            _non_empty(self.route_generation, "route_generation")
        if self.active_slot not in {None, "slot_a", "slot_b"}:
            raise ValueError("invalid active_slot")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


class DeploymentTrafficRouter(Protocol):
    """Optional Host-only adapter; never exposed as an Agent tool."""

    name: str

    def ensure_router(
        self,
        scope: TrafficRouterScope,
        port_bindings: tuple[TrafficPortBinding, ...],
        operation_id: str,
    ) -> TrafficRouterOperationResult: ...

    def inspect_router(self, scope: TrafficRouterScope) -> TrafficRouterOperationResult: ...

    def prepare_slot(
        self,
        router: TrafficRouterRecord,
        slot: RouterSlot,
        target: TrafficRouteTarget,
        operation_id: str,
    ) -> TrafficRouterOperationResult: ...

    def switch_active_slot(
        self,
        router: TrafficRouterRecord,
        *,
        expected_generation: str,
        expected_slot: RouterSlot,
        target_slot: RouterSlot,
        next_generation: str,
        operation_id: str,
    ) -> TrafficRouterOperationResult: ...

    def read_route(
        self,
        router: TrafficRouterRecord,
        *,
        expected_generation: str,
        expected_slot: RouterSlot,
        expected_target: TrafficRouteTarget,
    ) -> TrafficRouteReadback: ...

    def drain_slot(
        self,
        router: TrafficRouterRecord,
        slot: RouterSlot,
        operation_id: str,
    ) -> TrafficRouterOperationResult: ...

    def inspect_slot_connections(
        self,
        router: TrafficRouterRecord,
        slot: RouterSlot,
    ) -> TrafficSlotConnectionSnapshot: ...
