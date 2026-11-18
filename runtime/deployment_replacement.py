"""Granular host-owned deployment replacement capability contracts.

This module is intentionally declarative: it defines the durable phase vocabulary
and provider operations, but performs no runtime I/O or replacement itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from runtime.deployment_provider import (
    DeploymentOperationResult,
    DeploymentRecord,
    DeploymentRequest,
    HealthCheckResult,
)

ReplacementPhase = Literal[
    "prepared",
    "candidate_started",
    "candidate_healthy",
    "traffic_switch_pending",
    "traffic_switched",
    "previous_retired",
    "aborted",
    "needs_reconciliation",
]

_REPLACEMENT_PHASES = {
    "prepared",
    "candidate_started",
    "candidate_healthy",
    "traffic_switch_pending",
    "traffic_switched",
    "previous_retired",
    "aborted",
    "needs_reconciliation",
}


@dataclass(frozen=True)
class ReplacementJournalRecord:
    """Host-persistable snapshot of one replacement transaction phase.

    Runtime identities are opaque provider-issued immutable identifiers. They
    must never be inferred from mutable names, tags, or endpoints.
    """

    operation_id: str
    provider: str
    project: str
    environment: str
    target_deployment_id: str
    previous_deployment_id: str
    phase: ReplacementPhase
    created_at: str
    updated_at: str
    candidate_runtime_id: str | None = None
    previous_runtime_id: str | None = None
    effective_traffic_target: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "provider",
            "project",
            "environment",
            "target_deployment_id",
            "previous_deployment_id",
            "created_at",
            "updated_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.target_deployment_id == self.previous_deployment_id:
            raise ValueError("replacement target and previous deployment must differ")
        if self.phase not in _REPLACEMENT_PHASES:
            raise ValueError("invalid replacement phase")
        for name in (
            "candidate_runtime_id",
            "previous_runtime_id",
            "effective_traffic_target",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when provided")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")



TrafficReadbackStatus = Literal[
    "verified", "mismatch", "unavailable", "invalid_response", "unsupported", "not_found"
]


@dataclass(frozen=True)
class DeploymentTrafficReadback:
    """Read-only comparison of the durable Router registry and live selector."""

    provider: str
    status: TrafficReadbackStatus
    checked_at: str
    router_runtime_id: str | None
    registry_active_slot: Literal["slot_a", "slot_b"] | None
    registry_active_runtime_id: str | None
    live_active_slot: Literal["none", "slot_a", "slot_b"] | None
    effective_runtime_id: str | None
    route_generation: str | None
    detail: str = ""

    def __post_init__(self) -> None:
        for name in ("provider", "checked_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.status not in {
            "verified", "mismatch", "unavailable", "invalid_response",
            "unsupported", "not_found",
        }:
            raise ValueError("invalid traffic read-back status")
        for name in ("router_runtime_id", "registry_active_runtime_id", "effective_runtime_id"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            ):
                raise ValueError(f"{name} must be a full lowercase immutable runtime ID")
        if self.registry_active_slot not in {None, "slot_a", "slot_b"}:
            raise ValueError("invalid registry active slot")
        if self.live_active_slot not in {None, "none", "slot_a", "slot_b"}:
            raise ValueError("invalid live active slot")
        if self.route_generation is not None and (
            not isinstance(self.route_generation, str) or not self.route_generation.strip()
        ):
            raise ValueError("route_generation must be a non-empty string when provided")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")
        if self.status == "verified":
            if (
                self.router_runtime_id is None
                or self.route_generation is None
                or self.live_active_slot is None
                or self.live_active_slot != (self.registry_active_slot or "none")
                or self.effective_runtime_id != self.registry_active_runtime_id
            ):
                raise ValueError("verified traffic read-back must match live selector to durable Router registry")


class DeploymentReplacementProvider(Protocol):
    """Provider capability for ordered replacement, never an opaque rollback.

    Implementations must make each operation idempotent for operation_id and
    return immutable runtime identities. Host code persists each phase and
    verifies traffic read-back before it may retire the previous instance.
    """

    name: str

    def health_check(self, record: DeploymentRecord) -> HealthCheckResult: ...

    def immutable_runtime_id(self, record: DeploymentRecord) -> str | None: ...

    def prepare_candidate(
        self,
        request: DeploymentRequest,
        target: DeploymentRecord,
        previous: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult: ...

    def start_candidate(
        self,
        request: DeploymentRequest,
        target: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult: ...

    def verify_candidate(
        self,
        candidate: DeploymentRecord,
    ) -> HealthCheckResult: ...

    def switch_traffic(
        self,
        candidate: DeploymentRecord,
        previous: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult: ...

    def read_traffic_target(self, request: DeploymentRequest) -> str | None: ...

    def retire_previous(
        self,
        previous: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult: ...

    def abort_candidate(
        self,
        candidate: DeploymentRecord,
        operation_id: str,
    ) -> DeploymentOperationResult: ...
