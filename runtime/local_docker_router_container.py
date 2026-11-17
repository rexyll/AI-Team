"""Fixed Router container argv contract and exact Docker inspect verification.

This module is pure: it builds an allowlisted ``docker run`` argv and verifies
read-back data. It does not invoke Docker or create a persistent container.
"""
from __future__ import annotations
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_config import render_active_slot_map, render_haproxy_router_config
from runtime.local_docker_router_image import DockerRouterImageIdentity
from runtime.local_docker_router_network import DockerRouterNetworkRecord, build_router_network_spec
from runtime.local_docker_router_state import RouterStateRecord

_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_MANAGED_LABEL = "com.ai-team.router.managed"
_CONTRACT_LABEL = "com.ai-team.router.container-contract"
_SCOPE_LABEL = "com.ai-team.router.scope-sha256"
_NETWORK_LABEL = "com.ai-team.router.network-id"
_IMAGE_LABEL = "com.ai-team.router.image-id"
_CONFIG_DESTINATION = "/usr/local/etc/haproxy/haproxy.cfg"
_MAP_DESTINATION = "/usr/local/etc/haproxy/active-slot.map"
_EXPECTED_ENTRYPOINT = ["/docker-entrypoint.sh"]
_EXPECTED_COMMAND = ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]

ContainerVerificationStatus = Literal["verified", "mismatch", "invalid_response"]


def _safe_mount_path(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or any(ch in value for ch in (",", "\\x00", "\\r", "\\n")):
        raise ValueError(f"{name} must be an absolute path safe for Docker --mount syntax")
    return value


def _expected_container_labels(scope_fingerprint: str, network_id: str, image_id: str) -> tuple[tuple[str, str], ...]:
    return (
        (_MANAGED_LABEL, "true"),
        (_CONTRACT_LABEL, "1"),
        (_SCOPE_LABEL, scope_fingerprint),
        (_NETWORK_LABEL, network_id),
        (_IMAGE_LABEL, image_id),
    )


def _expected_container_capabilities(port_bindings: tuple[TrafficPortBinding, ...]) -> tuple[str, ...]:
    return ("NET_BIND_SERVICE",) if any(item.host_port < 1024 for item in port_bindings) else ()


def _build_run_argv(
    container_name: str, network_name: str, image_id: str,
    labels: tuple[tuple[str, str], ...], capabilities: tuple[str, ...],
    port_bindings: tuple[TrafficPortBinding, ...], config_path: str, map_path: str,
    container_uid: int, container_gid: int,
) -> tuple[str, ...]:
    argv: list[str] = ["run", "--detach", "--name", container_name,
                      "--user", f"{container_uid}:{container_gid}"]
    for key, value in labels:
        argv.extend(["--label", f"{key}={value}"])
    argv.extend(["--network", network_name, "--restart", "unless-stopped"])
    argv.extend(["--read-only", "--cap-drop", "ALL"])
    if capabilities:
        argv.extend(["--cap-add", "NET_BIND_SERVICE"])
    tmpfs_spec = (
        f"/run/haproxy:rw,noexec,nosuid,nodev,size=1m,"
        f"uid={container_uid},gid={container_gid},mode=700"
    )
    argv.extend(["--security-opt", "no-new-privileges:true", "--tmpfs", tmpfs_spec])
    argv.extend(["--mount", f"type=bind,src={config_path},dst={_CONFIG_DESTINATION},readonly"])
    argv.extend(["--mount", f"type=bind,src={map_path},dst={_MAP_DESTINATION},readonly"])
    for item in port_bindings:
        argv.extend(["--publish", f"0.0.0.0:{item.host_port}:{item.host_port}/tcp"])
    argv.append(image_id)
    return tuple(argv)
@dataclass(frozen=True)
class DockerRouterContainerSpec:
    container_name: str
    scope_fingerprint: str
    image_id: str
    network_name: str
    network_id: str
    container_uid: int
    container_gid: int
    port_bindings: tuple[TrafficPortBinding, ...]
    config_path: str
    active_slot_map_path: str
    labels: tuple[tuple[str, str], ...]
    capabilities: tuple[str, ...]
    run_argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.scope_fingerprint):
            raise ValueError("scope_fingerprint must be a full SHA-256 digest")
        if self.container_name != f"ai-team-router-c-{self.scope_fingerprint[:20]}":
            raise ValueError("Router container identity name is not deterministic for the scope")
        if self.network_name != f"ai-team-router-{self.scope_fingerprint[:20]}":
            raise ValueError("Router network name is not deterministic for the scope")
        if not _IMAGE_ID.fullmatch(self.image_id):
            raise ValueError("image_id must be a full immutable image ID")
        if not _CONTAINER_ID.fullmatch(self.network_id):
            raise ValueError("network_id must be a full immutable Docker network ID")
        for name in ("container_uid", "container_gid"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2**31 - 1:
                raise ValueError(f"{name} must be a non-negative container numeric identity")
        if not isinstance(self.port_bindings, tuple) or not self.port_bindings or any(not isinstance(x, TrafficPortBinding) for x in self.port_bindings):
            raise ValueError("port_bindings must be a non-empty tuple of TCP bindings")
        if tuple(sorted(self.port_bindings, key=lambda item: item.host_port)) != self.port_bindings:
            raise ValueError("port_bindings must be sorted by host port")
        if len({item.host_port for item in self.port_bindings}) != len(self.port_bindings):
            raise ValueError("port_bindings must have unique host ports")
        config_path = _safe_mount_path(self.config_path, "config_path")
        map_path = _safe_mount_path(self.active_slot_map_path, "active_slot_map_path")
        if Path(config_path).name != "haproxy.cfg" or Path(map_path).name != "active-slot.map" or Path(config_path).parent != Path(map_path).parent:
            raise ValueError("Router config and map files must be sibling files with fixed names")
        expected_labels = _expected_container_labels(self.scope_fingerprint, self.network_id, self.image_id)
        if self.labels != expected_labels:
            raise ValueError("Router container labels do not match the verified scope/network/image identity")
        expected_caps = _expected_container_capabilities(self.port_bindings)
        if self.capabilities != expected_caps:
            raise ValueError("Router container capabilities exceed the minimal host-port requirement")
        if not isinstance(self.run_argv, tuple) or any(not isinstance(x, str) or not x or "\\x00" in x for x in self.run_argv):
            raise ValueError("Router container argv must be an immutable sequence of safe strings")
        expected_argv = _build_run_argv(
            self.container_name, self.network_name, self.image_id, self.labels,
            self.capabilities, self.port_bindings, self.config_path, self.active_slot_map_path,
            self.container_uid, self.container_gid,
        )
        if self.run_argv != expected_argv:
            raise ValueError("Router container argv does not match the fixed allowlisted contract")


@dataclass(frozen=True)
class RouterContainerVerification:
    status: ContainerVerificationStatus
    container_id: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"verified", "mismatch", "invalid_response"}:
            raise ValueError("invalid Router container verification status")
        if self.status == "verified":
            if not isinstance(self.container_id, str) or not _CONTAINER_ID.fullmatch(self.container_id):
                raise ValueError("verified Router container requires a full immutable ID")
        elif self.container_id is not None:
            raise ValueError("unverified Router container must not expose a trusted ID")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


def _verified_state_owner(state: RouterStateRecord) -> tuple[int, int]:
    """Return the numeric Host owner used by private files and Router process.

    Host state remains 0700/0600. The Router runs as this exact UID/GID so it
    can read the read-only bind mounts without making those files world-readable.
    """
    directory = Path(state.directory)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
    ):
        raise ValueError("Router state directory must be Host-owned, real and mode 0700")
    for raw_path in (state.config_path, state.active_slot_map_path):
        file_info = Path(raw_path).lstat()
        if (
            not stat.S_ISREG(file_info.st_mode)
            or stat.S_ISLNK(file_info.st_mode)
            or file_info.st_uid != info.st_uid
            or file_info.st_gid != info.st_gid
            or file_info.st_nlink != 1
            or stat.S_IMODE(file_info.st_mode) != 0o600
        ):
            raise ValueError("Router state files must be singly linked Host-owned regular files mode 0600")
    return info.st_uid, info.st_gid


def build_router_container_spec(
    scope: TrafficRouterScope,
    port_bindings: tuple[TrafficPortBinding, ...],
    network: DockerRouterNetworkRecord,
    image: DockerRouterImageIdentity,
    state: RouterStateRecord,
) -> DockerRouterContainerSpec:
    """Build the single permitted Router container argv from verified inputs."""
    if not isinstance(scope, TrafficRouterScope):
        raise TypeError("scope must be a TrafficRouterScope")
    if not isinstance(network, DockerRouterNetworkRecord):
        raise TypeError("network must be a verified DockerRouterNetworkRecord")
    if not isinstance(image, DockerRouterImageIdentity):
        raise TypeError("image must be a verified DockerRouterImageIdentity")
    if not isinstance(state, RouterStateRecord):
        raise TypeError("state must be a persisted RouterStateRecord")
    if not isinstance(port_bindings, tuple) or not port_bindings or any(not isinstance(x, TrafficPortBinding) for x in port_bindings):
        raise ValueError("port_bindings must be a non-empty tuple of TrafficPortBinding values")
    ordered = tuple(sorted(port_bindings, key=lambda item: item.host_port))
    if len({item.host_port for item in ordered}) != len(ordered):
        raise ValueError("Router host ports must be unique")
    expected_scope = build_router_network_spec(scope)
    if network.network_name != expected_scope.network_name or network.scope_fingerprint != expected_scope.scope_fingerprint:
        raise ValueError("network identity does not match the requested Router scope")
    if state.network_name != expected_scope.network_name or state.scope_fingerprint != expected_scope.scope_fingerprint:
        raise ValueError("Router state directory does not match the requested scope")
    if state.directory_mode != 0o700 or state.file_mode != 0o600:
        raise ValueError("Router state permissions are not private")
    config = render_haproxy_router_config(ordered)
    initial_map = render_active_slot_map(None)
    if hashlib.sha256(config.encode("utf-8")).hexdigest() != state.config_sha256:
        raise ValueError("persisted HAProxy config hash does not match the requested TCP port bindings")
    if hashlib.sha256(initial_map.encode("utf-8")).hexdigest() != state.active_slot_map_sha256:
        raise ValueError("Router bootstrap map must have the fail-closed active none selector")
    config_path = _safe_mount_path(state.config_path, "config_path")
    map_path = _safe_mount_path(state.active_slot_map_path, "active_slot_map_path")
    container_uid, container_gid = _verified_state_owner(state)
    expected_dir = state.directory.rstrip("/") + "/"
    if not config_path.startswith(expected_dir) or not map_path.startswith(expected_dir):
        raise ValueError("Router state mount files must be contained in their scope directory")
    container_name = f"ai-team-router-c-{expected_scope.scope_fingerprint[:20]}"
    labels = _expected_container_labels(expected_scope.scope_fingerprint, network.network_id, image.image_id)
    capabilities = _expected_container_capabilities(ordered)
    argv = _build_run_argv(
        container_name, network.network_name, image.image_id, labels, capabilities,
        ordered, config_path, map_path, container_uid, container_gid,
    )
    return DockerRouterContainerSpec(
        container_name=container_name, scope_fingerprint=expected_scope.scope_fingerprint,
        image_id=image.image_id, network_name=network.network_name, network_id=network.network_id,
        port_bindings=ordered, config_path=config_path, active_slot_map_path=map_path,
        container_uid=container_uid, container_gid=container_gid,
        labels=labels, capabilities=capabilities, run_argv=argv,
    )


def _tmpfs_matches_identity(value: object, uid: int, gid: int) -> bool:
    if not isinstance(value, str):
        return False
    options = {item.strip() for item in value.split(",")}
    required = {
        f"uid={uid}", f"gid={gid}", "mode=700",
        "rw", "noexec", "nosuid", "nodev",
    }
    # Docker inspect preserves the accepted shorthand size=1m instead of
    # always normalizing it to bytes; both represent the same 1 MiB tmpfs cap.
    return required.issubset(options) and bool(
        {"size=1m", "size=1048576"}.intersection(options)
    )


def verify_router_container_inspection(payload: object, spec: DockerRouterContainerSpec) -> RouterContainerVerification:
    """Verify exact identity, mounts, security controls, network and published ports."""
    if not isinstance(spec, DockerRouterContainerSpec):
        raise TypeError("spec must be a DockerRouterContainerSpec")
    if not isinstance(payload, dict):
        return RouterContainerVerification("invalid_response", detail="Docker inspect must return one JSON object")
    container_id = payload.get("Id")
    if not isinstance(container_id, str) or not _CONTAINER_ID.fullmatch(container_id):
        return RouterContainerVerification("invalid_response", detail="Docker inspect returned an invalid immutable container ID")
    config = payload.get("Config")
    state = payload.get("State")
    host = payload.get("HostConfig")
    network_settings = payload.get("NetworkSettings")
    if not all(isinstance(item, dict) for item in (config, state, host, network_settings)):
        return RouterContainerVerification("invalid_response", detail="Docker inspect omitted Config, State, HostConfig or NetworkSettings")
    labels = config.get("Labels")
    if not isinstance(labels, dict):
        return RouterContainerVerification("invalid_response", detail="Docker inspect labels are malformed")
    expected_labels = dict(spec.labels)
    if (
        payload.get("Name") != f"/{spec.container_name}"
        or config.get("Image") != spec.image_id
        or config.get("Entrypoint") != _EXPECTED_ENTRYPOINT
        or config.get("Cmd") != _EXPECTED_COMMAND
        or config.get("User") != f"{spec.container_uid}:{spec.container_gid}"
        or any(labels.get(key) != value for key, value in expected_labels.items())
        or state.get("Running") is not True
    ):
        return RouterContainerVerification("mismatch", detail="Router container identity (name/image/labels/command/running state) mismatch")
    if (
        host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("CapDrop") != ["ALL"]
        or set(host.get("CapAdd") or []) != set(spec.capabilities)
        or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
        or host.get("NetworkMode") != spec.network_name
        or (host.get("RestartPolicy") or {}).get("Name") != "unless-stopped"
        or "/run/haproxy" not in (host.get("Tmpfs") or {})
        or not _tmpfs_matches_identity(
            (host.get("Tmpfs") or {}).get("/run/haproxy"),
            spec.container_uid, spec.container_gid,
        )
    ):
        return RouterContainerVerification("mismatch", detail="Router container security, network or restart policy mismatch")
    mounts = payload.get("Mounts")
    if not isinstance(mounts, list):
        return RouterContainerVerification("invalid_response", detail="Docker inspect mounts are malformed")
    expected_mounts = {
        (_CONFIG_DESTINATION, spec.config_path),
        (_MAP_DESTINATION, spec.active_slot_map_path),
    }
    observed_mounts = set()
    for mount in mounts:
        if not isinstance(mount, dict):
            return RouterContainerVerification("invalid_response", detail="Docker mount entry is malformed")
        observed_mounts.add((mount.get("Destination"), mount.get("Source")))
        if mount.get("Type") != "bind" or mount.get("RW") is not False:
            return RouterContainerVerification("mismatch", detail="Router config and map mounts must be read-only bind mounts")
    if observed_mounts != expected_mounts or len(mounts) != 2:
        return RouterContainerVerification("mismatch", detail="Router container has unexpected or missing bind mounts")
    networks = network_settings.get("Networks")
    if not isinstance(networks, dict) or set(networks) != {spec.network_name}:
        return RouterContainerVerification("mismatch", detail="Router container is not isolated to the expected scope network")
    attached = networks[spec.network_name]
    if not isinstance(attached, dict) or attached.get("NetworkID") != spec.network_id:
        return RouterContainerVerification("mismatch", detail="Router container network immutable ID does not match the verified scope network")
    expected_ports = {
        f"{item.host_port}/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(item.host_port)}]
        for item in spec.port_bindings
    }
    if host.get("PortBindings") != expected_ports:
        return RouterContainerVerification("mismatch", detail="Router published TCP port bindings do not match the scope contract")
    observed_ports = network_settings.get("Ports")
    if not isinstance(observed_ports, dict) or observed_ports != expected_ports:
        return RouterContainerVerification("mismatch", detail="Docker network port read-back does not match configured TCP bindings")
    return RouterContainerVerification("verified", container_id)
