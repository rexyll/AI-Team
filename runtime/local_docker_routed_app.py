"""Host-owned routed application container creation on a verified Router bridge.

This manager deliberately has no host-port publishing or route-switch operation.
It creates/inspects an app container on exactly one verified per-scope bridge,
then returns its immutable runtime identity and private-network endpoint. Traffic
switching remains a separate DeploymentTrafficRouter/Host transaction.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from runtime.deployment_provider import DeploymentArtifact
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouteTarget
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_network import DockerRouterNetworkRecord

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_DEPLOYMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CONTAINER_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
_NETWORK_NAME = re.compile(r"^ai-team-router-[0-9a-f]{20}$")
_PORT = re.compile(r"^[0-9]{1,5}/tcp$")

_MANAGED_LABEL = "com.ai-team.router.routed-app.managed"
_SCOPE_LABEL = "com.ai-team.router.scope-sha256"
_NETWORK_ID_LABEL = "com.ai-team.router.network-id"
_DEPLOYMENT_LABEL = "com.ai-team.router.deployment-id"
_IMAGE_ID_LABEL = "com.ai-team.router.image-id"
_PORTS_LABEL = "com.ai-team.router.port-bindings-sha256"

ROUTED_APP_CONTAINER_INSPECT_FORMAT = (
    r'{{$health := "null"}}'
    r'{{if .State.Health}}{{$status := .State.Health.Status}}{{$exitCode := -1}}{{$end := ""}}'
    r'{{range .State.Health.Log}}{{$exitCode = .ExitCode}}{{$end = .End}}{{end}}'
    r'{{$health = printf "{\"Status\":%q,\"Log\":[{\"ExitCode\":%d,\"End\":%q}]}" $status $exitCode $end}}{{end}}'
    r'{{printf "{\"Id\":%q,\"Name\":%q,\"Config\":{\"Image\":%q,\"Labels\":%s,'
    r'\"ExposedPorts\":%s,\"Volumes\":%s},\"State\":{\"Status\":%q,\"StartedAt\":%q,'
    r'\"Health\":%s},\"HostConfig\":{\"NetworkMode\":%q,\"Privileged\":%t,'
    r'\"PublishAllPorts\":%t,\"PortBindings\":%s,\"CapDrop\":%s,\"CapAdd\":%s,'
    r'\"SecurityOpt\":%s},\"Mounts\":%s,\"NetworkSettings\":{\"Networks\":%s,'
    r'\"Ports\":%s}}" .Id .Name .Config.Image (json .Config.Labels) '
    r'(json .Config.ExposedPorts) (json (index .Config "Volumes")) .State.Status '
    r'.State.StartedAt $health .HostConfig.NetworkMode '
    r'.HostConfig.Privileged .HostConfig.PublishAllPorts (json .HostConfig.PortBindings) '
    r'(json .HostConfig.CapDrop) (json .HostConfig.CapAdd) '
    r'(json .HostConfig.SecurityOpt) (json .Mounts) '
    r'(json .NetworkSettings.Networks) (json .NetworkSettings.Ports)}}'
)
ROUTED_APP_IMAGE_INSPECT_FORMAT = (
    r'{{printf "{\"Id\":%q,\"Config\":{\"Volumes\":%s}}" .Id (json (index .Config "Volumes"))}}'
)

EnsureStatus = Literal[
    "created", "existing", "unavailable", "failed", "mismatch", "invalid_response"
]
HealthStatus = Literal["healthy", "unhealthy", "unknown", "unavailable"]


@dataclass(frozen=True)
class DockerRoutedAppContainerSpec:
    """Fixed app-container invocation, pinned to one verified network/image."""

    deployment_id: str
    container_name: str
    network_name: str
    network_id: str
    scope_fingerprint: str
    image_id: str
    network_alias: str
    port_bindings: tuple[TrafficPortBinding, ...]
    labels: tuple[tuple[str, str], ...]
    capabilities: tuple[str, ...]
    run_argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.deployment_id, str) or not _DEPLOYMENT_ID.fullmatch(self.deployment_id):
            raise ValueError("deployment_id must contain only Docker-safe identity characters")
        if not isinstance(self.container_name, str) or not _CONTAINER_NAME.fullmatch(self.container_name):
            raise ValueError("container_name is invalid")
        if not isinstance(self.network_name, str) or not _NETWORK_NAME.fullmatch(self.network_name):
            raise ValueError("network_name must be a deterministic verified Router bridge name")
        for name in ("network_id", "scope_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} must be a full immutable SHA-256 identity")
        if not isinstance(self.image_id, str) or not _IMAGE_ID.fullmatch(self.image_id):
            raise ValueError("image_id must be a full immutable Docker image ID")
        if self.network_alias != self.container_name:
            raise ValueError("network_alias must be the deterministic container name")
        if not isinstance(self.port_bindings, tuple) or not self.port_bindings:
            raise ValueError("port_bindings must be a non-empty tuple")
        if any(not isinstance(item, TrafficPortBinding) for item in self.port_bindings):
            raise TypeError("port_bindings must contain TrafficPortBinding values")
        if len({item.host_port for item in self.port_bindings}) != len(self.port_bindings):
            raise ValueError("host ports must be unique")
        if len({item.container_port for item in self.port_bindings}) != len(self.port_bindings):
            raise ValueError("container ports must be unique")
        expected_caps = ("NET_BIND_SERVICE",) if any(
            item.container_port < 1024 for item in self.port_bindings
        ) else ()
        if not isinstance(self.capabilities, tuple) or self.capabilities != expected_caps:
            raise ValueError("routed app capabilities must be the minimum port-specific set")
        deployment_key = hashlib.sha256(self.deployment_id.encode("utf-8")).hexdigest()[:20]
        expected_name = f"ai-team-app-{self.scope_fingerprint[:10]}-{deployment_key}"
        if self.container_name != expected_name:
            raise ValueError("container_name must be derived from the scope and full deployment identity")
        if self.network_alias != expected_name:
            raise ValueError("network_alias must match the deterministic app container name")
        if not isinstance(self.labels, tuple) or tuple(sorted(self.labels)) != self.labels:
            raise ValueError("labels must be a sorted immutable tuple")
        if self.labels != _build_labels(
            self.deployment_id, self.network_id, self.scope_fingerprint,
            self.image_id, self.port_bindings,
        ):
            raise ValueError("labels must exactly bind the immutable app/network/port identities")
        expected_argv = _build_run_argv(
            self.container_name, self.network_name, self.network_alias,
            self.image_id, self.port_bindings, self.labels, self.capabilities,
        )
        if self.run_argv != expected_argv:
            raise ValueError("run_argv does not match the fixed no-host-publish routed app contract")


@dataclass(frozen=True)
class DockerRoutedAppVerification:
    status: Literal["verified", "mismatch", "invalid_response"]
    target: TrafficRouteTarget | None = None
    health_status: HealthStatus = "unknown"
    health_detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"verified", "mismatch", "invalid_response"}:
            raise ValueError("invalid routed app verification status")
        if self.status == "verified":
            if not isinstance(self.target, TrafficRouteTarget):
                raise ValueError("verified routed app requires a private-network route target")
        elif self.target is not None:
            raise ValueError("unverified routed app must not expose a trusted target")
        if self.health_status not in {"healthy", "unhealthy", "unknown", "unavailable"}:
            raise ValueError("invalid routed app health status")
        if not isinstance(self.health_detail, str):
            raise TypeError("health_detail must be a string")

    @property
    def route_eligible(self) -> bool:
        """Identity is verified separately; only a fresh healthy check permits routing."""
        return self.status == "verified" and self.health_status == "healthy"


@dataclass(frozen=True)
class DockerRoutedAppEnsureResult:
    status: EnsureStatus
    target: TrafficRouteTarget | None = None
    health_status: HealthStatus = "unknown"
    detail: str = ""
    health_detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {
            "created", "existing", "unavailable", "failed", "mismatch", "invalid_response"
        }:
            raise ValueError("invalid routed app ensure status")
        if self.status in {"created", "existing"}:
            if not isinstance(self.target, TrafficRouteTarget):
                raise ValueError("verified routed app result requires a route target")
        elif self.target is not None:
            raise ValueError("unverified routed app result must not expose a trusted target")
        if self.health_status not in {"healthy", "unhealthy", "unknown", "unavailable"}:
            raise ValueError("invalid routed app health status")
        if not isinstance(self.detail, str) or not isinstance(self.health_detail, str):
            raise TypeError("details must be strings")

    @property
    def route_eligible(self) -> bool:
        """True only when the container, endpoint and fresh health are all verified."""
        return self.status in {"created", "existing"} and self.target is not None and self.health_status == "healthy"


def _ports_digest(port_bindings: tuple[TrafficPortBinding, ...]) -> str:
    canonical = "\n".join(
        f"{item.host_port}:{item.container_port}/tcp"
        for item in sorted(port_bindings, key=lambda p: p.host_port)
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _build_labels(
    deployment_id: str,
    network_id: str,
    scope_fingerprint: str,
    image_id: str,
    port_bindings: tuple[TrafficPortBinding, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(sorted({
        _MANAGED_LABEL: "true",
        _SCOPE_LABEL: scope_fingerprint,
        _NETWORK_ID_LABEL: network_id,
        _DEPLOYMENT_LABEL: deployment_id,
        _IMAGE_ID_LABEL: image_id,
        _PORTS_LABEL: _ports_digest(port_bindings),
    }.items()))


def _build_run_argv(
    container_name: str,
    network_name: str,
    network_alias: str,
    image_id: str,
    port_bindings: tuple[TrafficPortBinding, ...],
    labels: tuple[tuple[str, str], ...],
    capabilities: tuple[str, ...],
) -> tuple[str, ...]:
    argv: list[str] = ["run", "--detach", "--name", container_name]
    for key, value in labels:
        argv.extend(["--label", f"{key}={value}"])
    argv.extend([
        "--network", network_name,
        "--network-alias", network_alias,
        "--restart", "unless-stopped",
        "--cap-drop", "ALL",
    ])
    for capability in capabilities:
        argv.extend(["--cap-add", capability])
    argv.extend(["--security-opt", "no-new-privileges:true"])
    for binding in sorted(port_bindings, key=lambda p: p.container_port):
        argv.extend(["--expose", f"{binding.container_port}/tcp"])
    argv.append(image_id)
    return tuple(argv)


def build_routed_app_container_spec(
    network: DockerRouterNetworkRecord,
    artifact: DeploymentArtifact,
    deployment_id: str,
    port_bindings: tuple[TrafficPortBinding, ...],
) -> DockerRoutedAppContainerSpec:
    """Build the only supported initial routed-app invocation.

    Host ports are data for the Router and are never emitted as Docker publish
    arguments for the application container.
    """
    if not isinstance(network, DockerRouterNetworkRecord):
        raise TypeError("network must be a verified DockerRouterNetworkRecord")
    if not isinstance(artifact, DeploymentArtifact):
        raise TypeError("artifact must be a DeploymentArtifact")
    if artifact.provider != "docker-local":
        raise ValueError("routed app artifact must belong to docker-local provider")
    if not _DEPLOYMENT_ID.fullmatch(deployment_id):
        raise ValueError("deployment_id must contain only Docker-safe identity characters")
    if not isinstance(port_bindings, tuple) or not port_bindings:
        raise ValueError("port_bindings must be a non-empty tuple")
    if any(not isinstance(item, TrafficPortBinding) for item in port_bindings):
        raise TypeError("port_bindings must contain TrafficPortBinding values")
    host_ports = [item.host_port for item in port_bindings]
    container_ports = [item.container_port for item in port_bindings]
    if len(host_ports) != len(set(host_ports)) or len(container_ports) != len(set(container_ports)):
        raise ValueError("host and container ports must each be unique")
    image_id = "sha256:" + artifact.digest
    if not _IMAGE_ID.fullmatch(image_id):
        raise ValueError("artifact digest must identify a full immutable image")
    deployment_key = hashlib.sha256(deployment_id.encode("utf-8")).hexdigest()[:20]
    container_name = f"ai-team-app-{network.scope_fingerprint[:10]}-{deployment_key}"
    network_alias = container_name
    labels = _build_labels(
        deployment_id, network.network_id, network.scope_fingerprint,
        image_id, port_bindings,
    )
    capabilities = ("NET_BIND_SERVICE",) if any(p.container_port < 1024 for p in port_bindings) else ()
    argv = _build_run_argv(
        container_name, network.network_name, network_alias,
        image_id, port_bindings, labels, capabilities,
    )
    return DockerRoutedAppContainerSpec(
        deployment_id=deployment_id,
        container_name=container_name,
        network_name=network.network_name,
        network_id=network.network_id,
        scope_fingerprint=network.scope_fingerprint,
        image_id=image_id,
        network_alias=network_alias,
        port_bindings=port_bindings,
        labels=labels,
        capabilities=capabilities,
        run_argv=argv,
    )


def _health_observation(state: object) -> tuple[HealthStatus, str]:
    if not isinstance(state, dict):
        return "unknown", "Docker inspect state is missing"
    health = state.get("Health")
    if health is None:
        return "unknown", "Image defines no Docker HEALTHCHECK"
    if not isinstance(health, dict):
        return "unknown", "Docker HEALTHCHECK data is malformed"
    status = health.get("Status")
    if status == "unhealthy":
        return "unhealthy", "Docker HEALTHCHECK reports unhealthy"
    if status != "healthy":
        return "unknown", f"Docker HEALTHCHECK state is {status!r}"
    logs = health.get("Log")
    started_at = state.get("StartedAt")
    if not isinstance(logs, list) or not logs or not isinstance(started_at, str):
        return "unknown", "Fresh Docker HEALTHCHECK observation is missing"
    last = logs[-1]
    if not isinstance(last, dict) or last.get("ExitCode") != 0:
        return "unknown", "Latest Docker HEALTHCHECK result is malformed or unsuccessful"
    end = last.get("End")
    if not isinstance(end, str) or not end.strip():
        return "unknown", "Docker HEALTHCHECK completion timestamp is missing"
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return "unknown", "Docker HEALTHCHECK timestamps are invalid"
    if (
        started.tzinfo is None
        or ended.tzinfo is None
        or ended <= started
        or ended > datetime.now(timezone.utc)
    ):
        return "unknown", "Docker HEALTHCHECK observation is not a valid completed check after container start"
    return "healthy", ""


def verify_routed_app_inspection(
    payload: object, spec: DockerRoutedAppContainerSpec
) -> DockerRoutedAppVerification:
    """Verify the app's immutable identity, one-network attachment and no-publish boundary."""
    if not isinstance(payload, dict):
        return DockerRoutedAppVerification(
            "invalid_response", health_detail="Docker app inspect must be one JSON object"
        )
    container_id = payload.get("Id")
    if not isinstance(container_id, str) or not _CONTAINER_ID.fullmatch(container_id):
        return DockerRoutedAppVerification(
            "invalid_response", health_detail="Docker app inspect has no full immutable container ID"
        )
    config = payload.get("Config")
    state = payload.get("State")
    host = payload.get("HostConfig")
    network_settings = payload.get("NetworkSettings")
    if not all(isinstance(item, dict) for item in (config, state, host, network_settings)):
        return DockerRoutedAppVerification(
            "invalid_response", health_detail="Docker app inspect omitted required objects"
        )
    labels = config.get("Labels")
    if not isinstance(labels, dict):
        return DockerRoutedAppVerification(
            "invalid_response", health_detail="Docker app inspect labels are missing"
        )
    expected_labels = dict(spec.labels)
    if (
        payload.get("Name") != "/" + spec.container_name
        or config.get("Image") != spec.image_id
        or any(labels.get(key) != value for key, value in expected_labels.items())
    ):
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Docker app name, image or managed scope labels mismatch"
        )
    if (
        state.get("Status") != "running"
        or host.get("NetworkMode") != spec.network_name
        or host.get("Privileged") is not False
        or host.get("PublishAllPorts") is not False
        or host.get("PortBindings") not in (None, {})
        or host.get("CapDrop") != ["ALL"]
        or (host.get("CapAdd") or []) != list(spec.capabilities)
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
    ):
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Docker app runtime security or no-host-publish contract mismatch"
        )
    expected_exposed = {f"{item.container_port}/tcp" for item in spec.port_bindings}
    exposed = config.get("ExposedPorts")
    if (
        not isinstance(exposed, dict)
        or not expected_exposed.issubset(exposed)
        or any(not isinstance(port, str) or not _PORT.fullmatch(port) for port in exposed)
    ):
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Docker app image does not expose every requested TCP port safely"
        )
    volumes = config.get("Volumes")
    if volumes not in (None, {}):
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Routed app images declaring Docker volumes are unsupported"
        )
    mounts = payload.get("Mounts")
    if not isinstance(mounts, list) or mounts:
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Routed app container must not have implicit or explicit mounts"
        )
    networks = network_settings.get("Networks")
    if not isinstance(networks, dict) or set(networks) != {spec.network_name}:
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Routed app must be attached to exactly its verified scope network"
        )
    endpoint = networks.get(spec.network_name)
    if not isinstance(endpoint, dict) or endpoint.get("NetworkID") != spec.network_id:
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Routed app network immutable identity mismatch"
        )
    aliases = endpoint.get("Aliases")
    if not isinstance(aliases, list) or spec.network_alias not in aliases:
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Routed app network alias is not verified"
        )
    address = endpoint.get("IPAddress")
    if not isinstance(address, str) or not address:
        address = endpoint.get("GlobalIPv6Address")
    try:
        ipaddress.ip_address(address)
    except (ValueError, TypeError):
        return DockerRoutedAppVerification(
            "invalid_response", health_detail="Docker app inspect did not return a valid private-network IP"
        )
    network_ports = network_settings.get("Ports")
    if not isinstance(network_ports, dict) or set(network_ports) != set(exposed):
        return DockerRoutedAppVerification(
            "invalid_response", health_detail="Docker app network port metadata does not match image-exposed ports"
        )
    if any(value not in (None, []) for value in network_ports.values()):
        return DockerRoutedAppVerification(
            "mismatch", health_detail="Docker app network ports unexpectedly have host bindings"
        )
    health_status, health_detail = _health_observation(state)
    try:
        target = TrafficRouteTarget(
            deployment_id=spec.deployment_id,
            runtime_id=container_id,
            address=address,
            port_bindings=spec.port_bindings,
        )
    except (TypeError, ValueError):
        return DockerRoutedAppVerification(
            "invalid_response", health_detail="Docker app route target could not be validated"
        )
    return DockerRoutedAppVerification(
        "verified", target, health_status, health_detail
    )


class LocalDockerRoutedAppManager:
    """Create/verify an app container on one Router bridge without publishing ports."""

    def __init__(self, provider: LocalDockerProvider) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        self.provider = provider

    @staticmethod
    def _is_missing(detail: str) -> bool:
        lowered = detail.lower()
        return "no such object" in lowered or "no such container" in lowered

    def _classify_error(self, detail: str) -> EnsureStatus:
        lowered = detail.lower()
        if self.provider._is_unavailable(detail) or "timed out" in lowered or "timeout" in lowered:
            return "unavailable"
        return "failed"

    def _verify_image(
        self, artifact: DeploymentArtifact, spec: DockerRoutedAppContainerSpec
    ) -> tuple[EnsureStatus | Literal["verified"], str]:
        result, error = self.provider._execute([
            "image", "inspect", "--format", ROUTED_APP_IMAGE_INSPECT_FORMAT,
            spec.image_id,
        ])
        if error:
            return self._classify_error(error), error
        assert result is not None
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            return self._classify_error(output), output or "Docker app image inspect failed"
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return "invalid_response", "Docker app image inspect returned malformed JSON"
        if not isinstance(payload, dict):
            return "invalid_response", "Docker app image inspect must return one object"
        if payload.get("Id") != spec.image_id:
            return "mismatch", "Docker app artifact does not resolve to the expected immutable image ID"
        config = payload.get("Config")
        if not isinstance(config, dict):
            return "invalid_response", "Docker app image inspect omitted Config"
        volumes = config.get("Volumes")
        if volumes not in (None, {}):
            return "mismatch", "Routed app images declaring Docker volumes are unsupported"
        return "verified", ""

    def _inspect(
        self, spec: DockerRoutedAppContainerSpec
    ) -> tuple[EnsureStatus | Literal["missing", "verified"], DockerRoutedAppVerification | None, str]:
        result, error = self.provider._execute([
            "container", "inspect", "--format",
            ROUTED_APP_CONTAINER_INSPECT_FORMAT, spec.container_name,
        ])
        if error:
            return self._classify_error(error), None, error
        assert result is not None
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            if self._is_missing(output):
                return "missing", None, output or "Routed app container does not exist"
            return self._classify_error(output), None, output or "Docker routed app inspect failed"
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return (
                "invalid_response",
                None,
                "Docker routed app inspect returned malformed JSON "
                f"(stdout_chars={len(result.stdout)}, stderr_chars={len(result.stderr)}, "
                f"error_pos={exc.pos}, line={exc.lineno}, column={exc.colno})",
            )
        except TypeError:
            return "invalid_response", None, "Docker routed app inspect returned malformed JSON (non-text output)"
        verification = verify_routed_app_inspection(payload, spec)
        if verification.status == "verified":
            return "verified", verification, ""
        return verification.status, None, verification.health_detail

    def ensure_app(
        self, spec: DockerRoutedAppContainerSpec, artifact: DeploymentArtifact
    ) -> DockerRoutedAppEnsureResult:
        """Inspect before create and after create; never publishes ports or switches routes."""
        if not isinstance(spec, DockerRoutedAppContainerSpec):
            raise TypeError("spec must be a DockerRoutedAppContainerSpec")
        if not isinstance(artifact, DeploymentArtifact):
            raise TypeError("artifact must be a DeploymentArtifact")
        if artifact.provider != "docker-local" or spec.image_id != "sha256:" + artifact.digest:
            return DockerRoutedAppEnsureResult(
                "mismatch", detail="Routed app artifact does not match the pinned immutable spec image"
            )
        image_status, image_detail = self._verify_image(artifact, spec)
        if image_status != "verified":
            return DockerRoutedAppEnsureResult(image_status, detail=image_detail)
        before_status, before, before_detail = self._inspect(spec)
        if before_status == "verified":
            assert before is not None and before.target is not None
            return DockerRoutedAppEnsureResult(
                "existing", before.target, before.health_status, health_detail=before.health_detail
            )
        if before_status != "missing":
            return DockerRoutedAppEnsureResult(before_status, detail=before_detail)

        created, error = self.provider._execute(spec.run_argv)
        create_succeeded = error is None and created is not None and created.returncode == 0
        create_detail = error or (
            ((created.stderr or created.stdout).strip())
            if created is not None else "Docker routed app create returned no result"
        )
        after_status, after, after_detail = self._inspect(spec)
        if after_status == "verified":
            assert after is not None and after.target is not None
            return DockerRoutedAppEnsureResult(
                "created" if create_succeeded else "existing",
                after.target,
                after.health_status,
                "" if create_succeeded else "Routed app verified after an ambiguous create response",
                after.health_detail,
            )
        if after_status == "missing":
            if create_succeeded:
                return DockerRoutedAppEnsureResult(
                    "invalid_response",
                    detail="Docker run reported success but routed app is absent on re-inspection",
                )
            return DockerRoutedAppEnsureResult(
                self._classify_error(create_detail),
                detail=(create_detail or after_detail)[:1000],
            )
        return DockerRoutedAppEnsureResult(
            after_status, detail=(after_detail or create_detail)[:1000]
        )
