"""Provider-neutral contracts for host-owned deployment operations.

This module defines data and protocol boundaries only. It deliberately does
not invoke Docker, a shell, a cloud API, or mutate deployment state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol

OperationStatus = Literal["succeeded", "failed", "unavailable", "unsupported"]
DeploymentStatus = Literal["prepared", "running", "stopped", "failed"]
HealthStatus = Literal["healthy", "unhealthy", "unknown", "unavailable"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DeploymentArtifact:
    """Immutable build output identity; digest is the content identity."""
    provider: str
    artifact_ref: str
    digest: str
    version: str

    def __post_init__(self) -> None:
        for name in ("provider", "artifact_ref", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.digest, str) or not _SHA256.fullmatch(self.digest):
            raise ValueError("digest must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True)
class DeploymentRequest:
    """Explicit request scope; providers must not infer environment or ports."""
    project_root: str
    project: str
    environment: str
    version: str
    ports: tuple[str, ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("project_root", "project", "environment", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.ports, tuple) or any(
            not isinstance(port, str) or not port.strip() for port in self.ports
        ):
            raise ValueError("ports must be a tuple of non-empty strings")
        if len(set(self.ports)) != len(self.ports):
            raise ValueError("ports must not contain duplicates")
        if not isinstance(self.labels, Mapping) or any(
            not isinstance(key, str) or not key.strip() or not isinstance(value, str)
            for key, value in self.labels.items()
        ):
            raise ValueError("labels must map non-empty strings to strings")


@dataclass(frozen=True)
class DeploymentRecord:
    """Auditable deployment identity persisted by the host, not an Agent."""
    deployment_id: str
    provider: str
    environment: str
    version: str
    artifact: DeploymentArtifact
    status: DeploymentStatus
    health_status: HealthStatus
    created_at: str
    endpoint: str | None = None
    previous_deployment_id: str | None = None
    project: str | None = None
    container_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("deployment_id", "provider", "environment", "version", "created_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.project is not None and (not isinstance(self.project, str) or not self.project.strip()):
            raise ValueError("project must be a non-empty string when provided")
        if self.container_id is not None and (
            not isinstance(self.container_id, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.container_id)
        ):
            raise ValueError("container_id must be a full lowercase Docker container ID when provided")
        if self.artifact.provider != self.provider:
            raise ValueError("deployment provider must match artifact provider")
        if self.status not in {"prepared", "running", "stopped", "failed"}:
            raise ValueError("invalid deployment status")
        if self.health_status not in {"healthy", "unhealthy", "unknown", "unavailable"}:
            raise ValueError("invalid health status")


@dataclass(frozen=True)
class HealthCheckResult:
    status: HealthStatus
    checked_at: str
    probe: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"healthy", "unhealthy", "unknown", "unavailable"}:
            raise ValueError("invalid health status")
        for name in ("checked_at", "probe"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


RuntimeInspectionStatus = Literal[
    "verified",
    "not_found",
    "identity_mismatch",
    "unavailable",
    "invalid_response",
]
RuntimeState = Literal[
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
    "unknown",
]


@dataclass(frozen=True)
class DeploymentRuntimeInspection:
    """Read-only observation of one provider-issued immutable runtime identity.

    Identity verification and application health are separate facts. A
    verified immutable ID does not prove that the runtime is healthy or that
    traffic is routed to it.
    """

    provider: str
    deployment_id: str
    expected_runtime_id: str | None
    observed_runtime_id: str | None
    identity_match: bool
    status: RuntimeInspectionStatus
    runtime_state: RuntimeState
    health_status: HealthStatus
    checked_at: str
    probe: str
    detail: str = ""

    def __post_init__(self) -> None:
        for name in ("provider", "deployment_id", "checked_at", "probe"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.expected_runtime_id is not None and (
            not isinstance(self.expected_runtime_id, str)
            or not _RUNTIME_ID.fullmatch(self.expected_runtime_id)
        ):
            raise ValueError("expected_runtime_id must be a full lowercase immutable runtime ID")
        if self.observed_runtime_id is not None and (
            not isinstance(self.observed_runtime_id, str)
            or not _RUNTIME_ID.fullmatch(self.observed_runtime_id)
        ):
            raise ValueError("observed_runtime_id must be a full lowercase immutable runtime ID")
        if not isinstance(self.identity_match, bool):
            raise TypeError("identity_match must be a bool")
        if self.status not in {
            "verified", "not_found", "identity_mismatch", "unavailable", "invalid_response"
        }:
            raise ValueError("invalid runtime inspection status")
        if self.runtime_state not in {
            "created", "running", "paused", "restarting", "removing",
            "exited", "dead", "unknown",
        }:
            raise ValueError("invalid runtime state")
        if self.health_status not in {"healthy", "unhealthy", "unknown", "unavailable"}:
            raise ValueError("invalid health status")
        if self.status == "verified":
            if (
                self.expected_runtime_id is None
                or not self.identity_match
                or self.observed_runtime_id != self.expected_runtime_id
            ):
                raise ValueError("verified inspection must match the expected immutable runtime ID")
        elif self.identity_match:
            raise ValueError("non-verified inspection cannot claim an identity match")
        if self.status == "identity_mismatch" and (
            self.expected_runtime_id is None
            or self.observed_runtime_id is None
            or self.observed_runtime_id == self.expected_runtime_id
        ):
            raise ValueError("identity mismatch must report a different observed runtime ID")
        if self.status == "not_found" and (
            self.expected_runtime_id is None or self.observed_runtime_id is not None
        ):
            raise ValueError("not-found inspection requires an expected ID and no observed ID")
        if self.health_status == "healthy" and (
            self.status != "verified" or self.runtime_state != "running"
        ):
            raise ValueError("healthy requires a verified running runtime")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


class DeploymentRuntimeInspector(Protocol):
    """Optional provider capability for read-only immutable runtime inspection."""

    name: str

    def inspect_runtime(self, record: DeploymentRecord) -> DeploymentRuntimeInspection: ...
    def inspect_runtime_identity(
        self, deployment_id: str, runtime_id: str
    ) -> DeploymentRuntimeInspection: ...


@dataclass(frozen=True)
class DeploymentOperationResult:
    operation: str
    status: OperationStatus
    provider: str
    message: str
    artifact: DeploymentArtifact | None = None
    record: DeploymentRecord | None = None
    health: HealthCheckResult | None = None
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("operation", "provider", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.status not in {"succeeded", "failed", "unavailable", "unsupported"}:
            raise ValueError("invalid operation status")
        if self.record is not None and self.record.provider != self.provider:
            raise ValueError("result provider must match deployment record provider")
        if self.artifact is not None and self.artifact.provider != self.provider:
            raise ValueError("result provider must match artifact provider")
        if not isinstance(self.details, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.details.items()
        ):
            raise ValueError("details must map strings to strings")


class DeploymentProvider(Protocol):
    """Host-owned provider interface; implementations own credentials and I/O."""
    name: str

    def build(self, request: DeploymentRequest) -> DeploymentOperationResult: ...
    def deploy(self, request: DeploymentRequest, artifact: DeploymentArtifact) -> DeploymentOperationResult: ...
    def health_check(self, record: DeploymentRecord) -> HealthCheckResult: ...
    def stop(self, record: DeploymentRecord) -> DeploymentOperationResult: ...
    def rollback(self, request: DeploymentRequest, previous: DeploymentRecord) -> DeploymentOperationResult: ...


def is_rollback_candidate(record: DeploymentRecord) -> bool:
    """Only a previously running, verified healthy deployment is rollbackable."""
    return (
        record.status == "running"
        and record.health_status == "healthy"
        and bool(record.deployment_id.strip())
        and record.container_id is not None
        and bool(re.fullmatch(r"[0-9a-f]{64}", record.container_id))
        and bool(_SHA256.fullmatch(record.artifact.digest))
    )
