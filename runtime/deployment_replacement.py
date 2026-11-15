"""Granular host-owned deployment replacement capability contracts.

This module is intentionally declarative: it defines the durable phase vocabulary
and provider operations, but performs no runtime I/O or replacement itself.
"""
from __future__ import annotations

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
    "traffic_switched",
    "previous_retired",
    "aborted",
    "needs_reconciliation",
]

_REPLACEMENT_PHASES = {
    "prepared",
    "candidate_started",
    "candidate_healthy",
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
