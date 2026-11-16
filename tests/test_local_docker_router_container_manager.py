from __future__ import annotations

import hashlib
import json

import pytest

from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_config import render_active_slot_map, render_haproxy_router_config
from runtime.local_docker_router_container import build_router_container_spec
from runtime.local_docker_router_image import (
    DockerRouterImageIdentity, ROUTER_BASE_IMAGE_REF, ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION,
)
from runtime.local_docker_router_network import DockerRouterNetworkRecord, build_router_network_spec
from runtime.local_docker_router_state import RouterStateRecord
from runtime.local_docker_router_container_manager import LocalDockerRouterContainerManager


class FakeRunner:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append((list(args), cwd, timeout))
        item = self.results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ok(stdout=""):
    return DockerCommandResult(0, stdout, "")


def failed(stderr):
    return DockerCommandResult(1, "", stderr)


def make_spec(tmp_path):
    scope = TrafficRouterScope("docker-local", "manager", "test")
    network_spec = build_router_network_spec(scope)
    network = DockerRouterNetworkRecord(
        network_spec.network_name, "b" * 64, network_spec.scope_fingerprint, "bridge", False, False
    )
    image = DockerRouterImageIdentity(
        "sha256:" + "a" * 64, "linux", "amd64", ROUTER_HAPROXY_VERSION,
        ROUTER_SOCAT_PACKAGE_VERSION, ROUTER_BASE_IMAGE_REF, "1",
    )
    directory = tmp_path / network_spec.network_name
    directory.mkdir()
    ports = (TrafficPortBinding(8080, 80), TrafficPortBinding(8443, 443))
    config = render_haproxy_router_config(ports)
    active_map = render_active_slot_map(None)
    config_path = directory / "haproxy.cfg"
    map_path = directory / "active-slot.map"
    state = RouterStateRecord(
        network_spec.network_name, network_spec.scope_fingerprint, str(directory),
        str(config_path), str(map_path), hashlib.sha256(config.encode()).hexdigest(),
        hashlib.sha256(active_map.encode()).hexdigest(), 0o700, 0o600,
    )
    return build_router_container_spec(scope, ports, network, image, state)


def inspect_payload(spec, **changes):
    ports = {
        f"{item.host_port}/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(item.host_port)}]
        for item in spec.port_bindings
    }
    payload = {
        "Id": "c" * 64,
        "Name": "/" + spec.container_name,
        "Config": {
            "Image": spec.image_id,
            "Entrypoint": ["/docker-entrypoint.sh"],
            "Cmd": ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"],
            "Labels": dict(spec.labels),
        },
        "State": {"Running": True},
        "HostConfig": {
            "ReadonlyRootfs": True, "Privileged": False, "CapDrop": ["ALL"],
            "CapAdd": list(spec.capabilities), "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": spec.network_name, "RestartPolicy": {"Name": "unless-stopped"},
            "Tmpfs": {"/run/haproxy": "rw,noexec,nosuid,nodev,size=1048576,mode=700"},
            "PortBindings": ports,
        },
        "Mounts": [
            {"Type": "bind", "Source": spec.config_path, "Destination": "/usr/local/etc/haproxy/haproxy.cfg", "RW": False},
            {"Type": "bind", "Source": spec.active_slot_map_path, "Destination": "/usr/local/etc/haproxy/active-slot.map", "RW": False},
        ],
        "NetworkSettings": {
            "Networks": {spec.network_name: {"NetworkID": spec.network_id}},
            "Ports": ports,
        },
    }
    payload.update(changes)
    return json.dumps(payload)


def manager_for(tmp_path, *results):
    runner = FakeRunner(*results)
    return LocalDockerRouterContainerManager(LocalDockerProvider(runner)), runner


def test_existing_verified_router_is_reused_without_create(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(tmp_path, ok(inspect_payload(spec)))
    result = manager.ensure_router(spec)
    assert result.status == "existing" and result.container_id == "c" * 64
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == ["container", "inspect", "--format", "{{json .}}", spec.container_name]


def test_absent_router_is_created_and_reinspected_by_exact_name(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(
        tmp_path,
        failed(f"Error response from daemon: No such object: {spec.container_name}"),
        ok("c" * 64 + "\n"),
        ok(inspect_payload(spec)),
    )
    result = manager.ensure_router(spec)
    assert result.status == "created" and result.container_id == "c" * 64
    assert runner.calls[1][0] == list(spec.run_argv)
    assert runner.calls[2][0] == ["container", "inspect", "--format", "{{json .}}", spec.container_name]
    assert all(args[0:2] in (["container", "inspect"], ["run"]) for args, _, _ in runner.calls)
    assert all("rm" not in args and "stop" not in args for args, _, _ in runner.calls)


def test_create_race_or_lost_response_is_resolved_by_verified_inspect(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(
        tmp_path,
        failed(f"No such object: {spec.container_name}"),
        failed("Error response from daemon: Conflict. The container name is already in use"),
        ok(inspect_payload(spec)),
    )
    result = manager.ensure_router(spec)
    assert result.status == "existing" and result.container_id == "c" * 64
    assert "ambiguous create response" in result.detail
    assert len(runner.calls) == 3


def test_existing_mismatched_router_is_not_replaced_or_removed(tmp_path):
    spec = make_spec(tmp_path)
    wrong = json.loads(inspect_payload(spec))
    wrong["Config"]["Image"] = "sha256:" + "d" * 64
    manager, runner = manager_for(tmp_path, ok(json.dumps(wrong)))
    result = manager.ensure_router(spec)
    assert result.status == "mismatch" and result.container_id is None
    assert len(runner.calls) == 1


def test_host_port_collision_stays_failed_and_does_not_remove_any_container(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(
        tmp_path,
        failed(f"No such object: {spec.container_name}"),
        failed("Bind for 0.0.0.0:8080 failed: port is already allocated"),
        failed(f"No such object: {spec.container_name}"),
    )
    result = manager.ensure_router(spec)
    assert result.status == "failed" and result.container_id is None
    assert len(runner.calls) == 3
    assert all(args[0] != "rm" and args[0] != "stop" for args, _, _ in runner.calls)


def test_successful_create_without_inspectable_container_is_invalid_response(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(
        tmp_path,
        failed(f"No such object: {spec.container_name}"),
        ok("container-id\n"),
        failed(f"No such object: {spec.container_name}"),
    )
    result = manager.ensure_router(spec)
    assert result.status == "invalid_response" and result.container_id is None


def test_create_timeout_with_absent_container_is_unavailable(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(
        tmp_path,
        failed(f"No such object: {spec.container_name}"),
        DockerCommandResult(124, "", "Docker command timed out after 600 seconds"),
        failed(f"No such object: {spec.container_name}"),
    )
    result = manager.ensure_router(spec)
    assert result.status == "unavailable" and result.container_id is None


def test_docker_daemon_unavailable_before_inspect_does_not_attempt_create(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(tmp_path, failed("Cannot connect to the Docker daemon"))
    result = manager.ensure_router(spec)
    assert result.status == "unavailable" and len(runner.calls) == 1


def test_missing_docker_executable_is_unavailable(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(tmp_path, FileNotFoundError())
    result = manager.ensure_router(spec)
    assert result.status == "unavailable" and len(runner.calls) == 1


def test_malformed_inspect_is_not_treated_as_missing(tmp_path):
    spec = make_spec(tmp_path)
    manager, runner = manager_for(tmp_path, ok("{broken"))
    result = manager.ensure_router(spec)
    assert result.status == "invalid_response" and len(runner.calls) == 1


def test_post_create_inspect_mismatch_is_not_trusted_or_cleaned_up(tmp_path):
    spec = make_spec(tmp_path)
    wrong = json.loads(inspect_payload(spec))
    wrong["NetworkSettings"]["Networks"][spec.network_name]["NetworkID"] = "d" * 64
    manager, runner = manager_for(
        tmp_path,
        failed(f"No such object: {spec.container_name}"),
        ok("container-id\n"),
        ok(json.dumps(wrong)),
    )
    result = manager.ensure_router(spec)
    assert result.status == "mismatch" and result.container_id is None
    assert len(runner.calls) == 3
    assert all(args[0] not in {"rm", "stop"} for args, _, _ in runner.calls)


def test_manager_requires_container_spec(tmp_path):
    manager, _ = manager_for(tmp_path)
    with pytest.raises(TypeError, match="DockerRouterContainerSpec"):
        manager.ensure_router(object())
