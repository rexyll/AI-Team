from __future__ import annotations
import hashlib
import json

import pytest

from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_image import DockerRouterImageIdentity, ROUTER_BASE_IMAGE_REF, ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION
from runtime.local_docker_router_network import DockerRouterNetworkRecord, build_router_network_spec
from runtime.local_docker_router_state import RouterStateRecord, _SERVER_STATE_HEADER
from runtime.local_docker_router_config import render_active_slot_map, render_haproxy_router_config
from runtime.local_docker_router_container import build_router_container_spec, verify_router_container_inspection

def scope():
    return TrafficRouterScope("docker-local", "robot", "dev")

def bindings(low=False):
    return (TrafficPortBinding(8080, 80), TrafficPortBinding(8443, 443)) if not low else (TrafficPortBinding(80, 80), TrafficPortBinding(8443, 443))

def verified_inputs(tmp_path, port_bindings=None, active_slot=None):
    scope_value = scope()
    network_spec = build_router_network_spec(scope_value)
    network = DockerRouterNetworkRecord(network_spec.network_name, "b" * 64, network_spec.scope_fingerprint, "bridge", False, False)
    image = DockerRouterImageIdentity("sha256:" + "a" * 64, "linux", "amd64", ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION, ROUTER_BASE_IMAGE_REF, "1")
    directory = tmp_path / network_spec.network_name
    directory.mkdir(mode=0o700)
    config = render_haproxy_router_config(port_bindings or bindings())
    active_map = render_active_slot_map(active_slot)
    config_path = directory / "haproxy.cfg"
    map_path = directory / "active-slot.map"
    config_path.write_text(config, encoding="utf-8")
    map_path.write_text(active_map, encoding="utf-8")
    (directory / "servers-state").write_text(_SERVER_STATE_HEADER, encoding="utf-8")
    (directory / "servers-state").chmod(0o600)
    config_path.chmod(0o600)
    map_path.chmod(0o600)
    server_state_sha256 = hashlib.sha256((directory / "servers-state").read_bytes()).hexdigest()
    state = RouterStateRecord(
        network_spec.network_name, network_spec.scope_fingerprint, str(directory),
        str(config_path), str(map_path), hashlib.sha256(config.encode()).hexdigest(),
        hashlib.sha256(active_map.encode()).hexdigest(), 0o700, 0o600,
        server_state_sha256,
    )
    return scope_value, port_bindings or bindings(), network, image, state

def make_inspect(spec):
    ports = {f"{item.host_port}/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(item.host_port)}] for item in spec.port_bindings}
    return {
        "Id": "c" * 64,
        "Name": "/" + spec.container_name,
        "Config": {
            "Image": spec.image_id,
            "User": f"{spec.container_uid}:{spec.container_gid}",
            "Entrypoint": ["/docker-entrypoint.sh"],
            "Cmd": ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"],
            "Labels": dict(spec.labels),
        },
        "State": {"Running": True},
        "HostConfig": {
            "ReadonlyRootfs": True, "Privileged": False, "CapDrop": ["ALL"],
            "CapAdd": list(spec.capabilities), "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": spec.network_name, "RestartPolicy": {"Name": "unless-stopped"},
            "Tmpfs": {"/run/haproxy": f"rw,noexec,nosuid,nodev,size=1048576,uid={spec.container_uid},gid={spec.container_gid},mode=700"},
            "PortBindings": ports,
        },
        "Mounts": [
            {"Type": "bind", "Source": spec.state_directory, "Destination": "/usr/local/etc/haproxy", "RW": False},
        ],
        "NetworkSettings": {
            "Networks": {spec.network_name: {"NetworkID": spec.network_id}},
            "Ports": ports,
        },
    }

def test_router_container_argv_uses_immutable_ids_readonly_mounts_and_no_privilege(tmp_path):
    spec = build_router_container_spec(*verified_inputs(tmp_path))
    argv = list(spec.run_argv)
    assert argv[:3] == ["run", "--detach", "--name"]
    assert spec.image_id == argv[-1] and argv[-1].startswith("sha256:")
    assert "--read-only" in argv and "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "--privileged" not in argv
    assert argv.count("--mount") == 1
    assert argv[argv.index("--mount") + 1] == f"type=bind,src={spec.state_directory},dst=/usr/local/etc/haproxy,readonly"
    assert all("readonly" in argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--mount")
    assert argv.count("--publish") == 2
    assert all("/tcp" in argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--publish")

def test_router_container_spec_adds_only_bind_service_for_privileged_ports(tmp_path):
    spec = build_router_container_spec(*verified_inputs(tmp_path, bindings(low=True)))
    assert spec.capabilities == ("NET_BIND_SERVICE",)
    assert spec.run_argv.count("--cap-add") == 1
    assert spec.run_argv[spec.run_argv.index("--cap-add") + 1] == "NET_BIND_SERVICE"

def test_router_container_spec_has_no_extra_capabilities_for_high_ports(tmp_path):
    spec = build_router_container_spec(*verified_inputs(tmp_path))
    assert spec.capabilities == ()
    assert "--cap-add" not in spec.run_argv

def test_router_container_spec_rejects_scope_network_mismatch(tmp_path):
    scope_value, ports, network, image, state = verified_inputs(tmp_path)
    wrong = DockerRouterNetworkRecord(network.network_name, network.network_id, "d" * 64, "bridge", False, False)
    with pytest.raises(ValueError, match="network identity"):
        build_router_container_spec(scope_value, ports, wrong, image, state)

def test_router_container_spec_rejects_state_hash_mismatch(tmp_path):
    scope_value, ports, network, image, state = verified_inputs(tmp_path)
    wrong_state = RouterStateRecord(state.network_name, state.scope_fingerprint, state.directory, state.config_path, state.active_slot_map_path, "e" * 64, state.active_slot_map_sha256, 0o700, 0o600)
    with pytest.raises(ValueError, match="config hash"):
        build_router_container_spec(scope_value, ports, network, image, wrong_state)

def test_router_container_spec_rejects_map_selector_mismatch(tmp_path):
    scope_value, ports, network, image, state = verified_inputs(tmp_path)
    wrong_state = RouterStateRecord(
        state.network_name, state.scope_fingerprint, state.directory,
        state.config_path, state.active_slot_map_path, state.config_sha256,
        hashlib.sha256(b"active slot_a\n").hexdigest(), 0o700, 0o600,
        state.server_state_sha256,
    )
    with pytest.raises(ValueError, match="expected selector"):
        build_router_container_spec(
            scope_value, ports, network, image, wrong_state,
            expected_active_slot=None,
        )

def test_direct_container_spec_construction_cannot_bypass_fixed_argv(tmp_path):
    from dataclasses import replace
    spec = build_router_container_spec(*verified_inputs(tmp_path))
    with pytest.raises(ValueError, match="fixed allowlisted contract"):
        replace(spec, run_argv=spec.run_argv + ("--privileged",))
    with pytest.raises(ValueError, match="minimal host-port requirement"):
        replace(spec, capabilities=("SYS_ADMIN",))
    with pytest.raises(ValueError, match="labels"):
        replace(spec, labels=(( "com.ai-team.router.managed", "false"),))

def test_valid_docker_inspect_accepts_docker_tmpfs_size_shorthand(tmp_path):
    spec = build_router_container_spec(*verified_inputs(tmp_path))
    payload = make_inspect(spec)
    payload["HostConfig"]["Tmpfs"]["/run/haproxy"] = (
        f"rw,noexec,nosuid,nodev,size=1m,uid={spec.container_uid},"
        f"gid={spec.container_gid},mode=700"
    )
    result = verify_router_container_inspection(payload, spec)
    assert result.status == "verified" and result.container_id == "c" * 64


def test_valid_docker_inspect_readback_verifies_container_identity_and_ports(tmp_path):
    spec = build_router_container_spec(*verified_inputs(tmp_path))
    result = verify_router_container_inspection(make_inspect(spec), spec)
    assert result.status == "verified" and result.container_id == "c" * 64

@pytest.mark.parametrize("mutator,match", [
    (lambda p: p.update({"Name": "/other"}), "identity"),
    (lambda p: p["Config"].update({"Image": "sha256:" + "d" * 64}), "identity"),
    (lambda p: p["Config"].update({"User": "99:99"}), "identity"),
    (lambda p: p["State"].update({"Running": False}), "identity"),
    (lambda p: p["HostConfig"].update({"ReadonlyRootfs": False}), "security"),
    (lambda p: p["HostConfig"].update({"Privileged": True}), "security"),
    (lambda p: p["HostConfig"].update({"NetworkMode": "bridge"}), "security"),
    (lambda p: p["NetworkSettings"]["Networks"][next(iter(p["NetworkSettings"]["Networks"]))].update({"NetworkID": "d" * 64}), "network immutable ID"),
    (lambda p: p["HostConfig"].update({"PortBindings": {}}), "TCP port bindings"),
    (lambda p: p["Mounts"][0].update({"RW": True}), "read-only bind mount"),
])
def test_inspect_mismatch_fails_closed(tmp_path, mutator, match):
    spec = build_router_container_spec(*verified_inputs(tmp_path))
    payload = make_inspect(spec)
    mutator(payload)
    result = verify_router_container_inspection(payload, spec)
    assert result.status == "mismatch" and result.container_id is None
    assert match in result.detail

def test_malformed_inspect_does_not_expose_container_id(tmp_path):
    spec = build_router_container_spec(*verified_inputs(tmp_path))
    result = verify_router_container_inspection([], spec)
    assert result.status == "invalid_response" and result.container_id is None


@pytest.mark.parametrize("active_slot", ["slot_a", "slot_b"])
def test_router_container_spec_accepts_a_digest_bound_persisted_active_selector(tmp_path, active_slot):
    inputs = verified_inputs(tmp_path, active_slot=active_slot)
    spec = build_router_container_spec(
        *inputs, expected_active_slot=active_slot
    )
    assert spec.active_slot_map_path.endswith("active-slot.map")
