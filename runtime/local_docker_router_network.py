"""Host-owned, fail-closed Docker user-defined bridge network management.

The manager only creates or verifies a per-project/environment bridge network.
It never falls back to Docker's default bridge, publishes ports, connects app
containers, or creates/stops a Router container.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from runtime.deployment_traffic_router import TrafficRouterScope
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider

_ROUTER_MANAGED_LABEL = "com.ai-team.router.managed"
_SCOPE_FINGERPRINT_LABEL = "com.ai-team.router.scope-sha256"
_NETWORK_ID = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_NAME = re.compile(r"^ai-team-router-[0-9a-f]{20}$")

NetworkStatus = Literal[
    "created", "existing", "unavailable", "failed", "mismatch", "invalid_response"
]


@dataclass(frozen=True)
class DockerRouterNetworkSpec:
    """Deterministic, non-reversible network identity for one Router scope."""

    network_name: str
    scope_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.network_name, str) or not _NETWORK_NAME.fullmatch(self.network_name):
            raise ValueError("network_name must be a deterministic AI-Team Router network name")
        if (
            not isinstance(self.scope_fingerprint, str)
            or not _NETWORK_ID.fullmatch(self.scope_fingerprint)
        ):
            raise ValueError("scope_fingerprint must be a full SHA-256 hex digest")


@dataclass(frozen=True)
class DockerRouterNetworkRecord:
    """Docker-observed network identity after exact Host scope verification."""

    network_name: str
    network_id: str
    scope_fingerprint: str
    driver: Literal["bridge"]
    internal: bool
    attachable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.network_name, str) or not _NETWORK_NAME.fullmatch(self.network_name):
            raise ValueError("network_name is invalid")
        if not isinstance(self.network_id, str) or not _NETWORK_ID.fullmatch(self.network_id):
            raise ValueError("network_id must be a full immutable Docker network ID")
        if (
            not isinstance(self.scope_fingerprint, str)
            or not _NETWORK_ID.fullmatch(self.scope_fingerprint)
        ):
            raise ValueError("scope_fingerprint must be a full SHA-256 hex digest")
        if self.driver != "bridge":
            raise ValueError("Router network driver must be bridge")
        if self.internal is not False or self.attachable is not False:
            raise ValueError("Router network must be non-internal and non-attachable")


@dataclass(frozen=True)
class DockerRouterNetworkResult:
    status: NetworkStatus
    spec: DockerRouterNetworkSpec
    record: DockerRouterNetworkRecord | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {
            "created", "existing", "unavailable", "failed", "mismatch", "invalid_response"
        }:
            raise ValueError("invalid Router network result status")
        if not isinstance(self.spec, DockerRouterNetworkSpec):
            raise TypeError("spec must be a DockerRouterNetworkSpec")
        if self.status in {"created", "existing"}:
            if not isinstance(self.record, DockerRouterNetworkRecord):
                raise ValueError("verified network results require a network record")
            if (
                self.record.network_name != self.spec.network_name
                or self.record.scope_fingerprint != self.spec.scope_fingerprint
            ):
                raise ValueError("verified network record must match the requested scope")
        elif self.record is not None:
            raise ValueError("unverified network results must not expose a trusted record")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


def build_router_network_spec(scope: TrafficRouterScope) -> DockerRouterNetworkSpec:
    """Create a stable scope-specific name without leaking project/environment names."""
    if not isinstance(scope, TrafficRouterScope):
        raise TypeError("scope must be a TrafficRouterScope")
    canonical_scope = json.dumps(
        [scope.provider, scope.project, scope.environment],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(canonical_scope.encode("utf-8")).hexdigest()
    return DockerRouterNetworkSpec(
        network_name=f"ai-team-router-{fingerprint[:20]}",
        scope_fingerprint=fingerprint,
    )


def _is_missing_network(output: str) -> bool:
    lowered = output.lower()
    return "no such network" in lowered or (
        "network" in lowered and "not found" in lowered
    )


def _is_unavailable(provider: LocalDockerProvider, message: str) -> bool:
    lowered = message.lower()
    return (
        provider._is_unavailable(message)
        or "timed out" in lowered
        or "timeout" in lowered
    )


class LocalDockerRouterNetworkManager:
    """Idempotently ensure one labeled, user-defined bridge network per scope."""

    def __init__(self, provider: LocalDockerProvider) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        self.provider = provider

    @staticmethod
    def _inspect_args(spec: DockerRouterNetworkSpec) -> list[str]:
        return ["network", "inspect", "--format", "{{json .}}", spec.network_name]

    @staticmethod
    def _create_args(spec: DockerRouterNetworkSpec) -> list[str]:
        return [
            "network", "create",
            "--driver", "bridge",
            "--label", f"{_ROUTER_MANAGED_LABEL}=true",
            "--label", f"{_SCOPE_FINGERPRINT_LABEL}={spec.scope_fingerprint}",
            spec.network_name,
        ]

    def _inspect(
        self, spec: DockerRouterNetworkSpec
    ) -> tuple[str, DockerRouterNetworkRecord | None, str]:
        result, error = self.provider._execute(self._inspect_args(spec))
        if error:
            status = "unavailable" if _is_unavailable(self.provider, error) else "failed"
            return status, None, error
        assert result is not None
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            if _is_missing_network(output):
                return "missing", None, output or "Router network does not exist"
            status = "unavailable" if _is_unavailable(self.provider, output) else "failed"
            return status, None, output or "Docker network inspect failed"
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return "invalid_response", None, "Docker network inspect returned malformed JSON"
        if not isinstance(payload, dict):
            return "invalid_response", None, "Docker network inspect must return one JSON object"
        network_id = payload.get("Id")
        if not isinstance(network_id, str) or not _NETWORK_ID.fullmatch(network_id):
            return "invalid_response", None, "Docker network inspect returned an invalid immutable ID"
        labels = payload.get("Labels")
        if not isinstance(labels, dict):
            return "invalid_response", None, "Docker network inspect returned invalid labels"
        if (
            payload.get("Name") != spec.network_name
            or payload.get("Driver") != "bridge"
            or payload.get("Scope") != "local"
            or payload.get("Internal") is not False
            or payload.get("Attachable") is not False
            or labels.get(_ROUTER_MANAGED_LABEL) != "true"
            or labels.get(_SCOPE_FINGERPRINT_LABEL) != spec.scope_fingerprint
        ):
            return "mismatch", None, "existing Docker network does not match the Router scope contract"
        record = DockerRouterNetworkRecord(
            network_name=spec.network_name,
            network_id=network_id,
            scope_fingerprint=spec.scope_fingerprint,
            driver="bridge",
            internal=False,
            attachable=False,
        )
        return "verified", record, ""

    def ensure_network(self, scope: TrafficRouterScope) -> DockerRouterNetworkResult:
        """Inspect, create only when absent, and always verify the resulting network."""
        spec = build_router_network_spec(scope)
        inspect_status, record, detail = self._inspect(spec)
        if inspect_status == "verified":
            return DockerRouterNetworkResult("existing", spec, record)
        if inspect_status != "missing":
            return DockerRouterNetworkResult(inspect_status, spec, detail=detail)  # type: ignore[arg-type]

        create_result, create_error = self.provider._execute(self._create_args(spec))
        create_succeeded = (
            create_error is None
            and create_result is not None
            and create_result.returncode == 0
        )
        # Re-inspection resolves create races and ambiguous client failures without
        # assuming that a successful CLI exit proves the desired network exists.
        after_status, after_record, after_detail = self._inspect(spec)
        if after_status == "verified":
            return DockerRouterNetworkResult(
                "created" if create_succeeded else "existing",
                spec,
                after_record,
                "" if create_succeeded else "verified concurrently after a non-successful create response",
            )
        if after_status == "missing":
            create_message = create_error or (
                (create_result.stderr or create_result.stdout).strip()
                if create_result is not None else "Docker network create did not return a result"
            )
            status = "unavailable" if _is_unavailable(self.provider, create_message) else "failed"
            return DockerRouterNetworkResult(
                status, spec, detail=create_message or "Router network remains absent"
            )
        return DockerRouterNetworkResult(
            after_status, spec, detail=after_detail or "Router network could not be verified after create"
        )  # type: ignore[arg-type]
