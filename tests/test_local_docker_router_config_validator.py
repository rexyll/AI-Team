from __future__ import annotations
import hashlib
import os

import pytest

from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_image import DockerRouterImageIdentity, ROUTER_BASE_IMAGE_REF, ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION
from runtime.local_docker_router_state import LocalDockerRouterStateStore
from runtime.local_docker_router_config_validator import LocalDockerRouterConfigValidator

class FakeRunner:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append((list(args), cwd, timeout))
        if isinstance(self.error, BaseException):
            raise self.error
        if self.error:
            # A reachable Docker CLI reports daemon connection failures as a
            # normal non-zero command result; only executable/OS failures raise.
            return DockerCommandResult(1, "", str(self.error))
        return self.result

def image():
    return DockerRouterImageIdentity("sha256:" + "a" * 64, "linux", "amd64", ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION, ROUTER_BASE_IMAGE_REF, "1")

def prepare_state(tmp_path):
    scope = TrafficRouterScope("docker-local", "haproxy-config", "test")
    ports = (TrafficPortBinding(18080, 80), TrafficPortBinding(18443, 443))
    result = LocalDockerRouterStateStore(tmp_path / "state").persist(scope, ports)
    assert result.status == "persisted" and result.record is not None
    return result.record

def test_validates_generated_config_with_verified_image_id_and_readonly_isolated_mounts(tmp_path):
    state = prepare_state(tmp_path)
    runner = FakeRunner(DockerCommandResult(0, "Configuration file is valid\n", ""))
    result = LocalDockerRouterConfigValidator(LocalDockerProvider(runner)).validate(image(), state)
    assert result.status == "valid"
    args = runner.calls[0][0]
    assert args[:7] == ["run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL"]
    assert args[args.index("--user") + 1] == f"{os.geteuid()}:{os.stat(state.directory).st_gid}"
    assert "uid=" in args[args.index("--tmpfs") + 1]
    assert args[args.index("--entrypoint") + 1] == "/usr/local/sbin/haproxy"
    assert args[args.index("--entrypoint") + 2] == image().image_id
    assert args[-3:] == ["-c", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]
    mounts = [args[i + 1] for i, value in enumerate(args[:-1]) if value == "--mount"]
    assert len(mounts) == 2 and all(item.endswith(",readonly") for item in mounts)
    assert "--publish" not in args and "--privileged" not in args

def test_haproxy_syntax_error_is_reported_as_invalid_config(tmp_path):
    state = prepare_state(tmp_path)
    runner = FakeRunner(DockerCommandResult(1, "", "parsing [haproxy.cfg:1] : error\n"))
    result = LocalDockerRouterConfigValidator(LocalDockerProvider(runner)).validate(image(), state)
    assert result.status == "invalid_config" and "error" in result.detail

def test_config_file_hash_mismatch_fails_before_docker_call(tmp_path):
    state = prepare_state(tmp_path)
    with open(state.config_path, "a", encoding="utf-8") as stream:
        stream.write("# tampered\n")
    runner = FakeRunner(DockerCommandResult(0, "", ""))
    result = LocalDockerRouterConfigValidator(LocalDockerProvider(runner)).validate(image(), state)
    assert result.status == "invalid_state" and runner.calls == []

def test_non_initial_active_map_is_rejected_before_docker_call(tmp_path):
    state = prepare_state(tmp_path)
    with open(state.active_slot_map_path, "w", encoding="utf-8") as stream:
        stream.write("active slot_a\n")
    os.chmod(state.active_slot_map_path, 0o600)
    modified = type(state)(state.network_name, state.scope_fingerprint, state.directory, state.config_path, state.active_slot_map_path, state.config_sha256, hashlib.sha256(b"active slot_a\n").hexdigest(), 0o700, 0o600)
    runner = FakeRunner(DockerCommandResult(0, "", ""))
    result = LocalDockerRouterConfigValidator(LocalDockerProvider(runner)).validate(image(), modified)
    assert result.status == "invalid_state" and runner.calls == []

def test_symlink_config_is_rejected(tmp_path):
    state = prepare_state(tmp_path)
    outside = tmp_path / "external.cfg"
    outside.write_text("global\n", encoding="utf-8")
    os.chmod(outside, 0o600)
    os.unlink(state.config_path)
    os.symlink(outside, state.config_path)
    runner = FakeRunner(DockerCommandResult(0, "", ""))
    result = LocalDockerRouterConfigValidator(LocalDockerProvider(runner)).validate(image(), state)
    assert result.status == "invalid_state" and runner.calls == []

def test_docker_daemon_unavailable_is_not_a_config_failure(tmp_path):
    state = prepare_state(tmp_path)
    runner = FakeRunner(error="Cannot connect to the Docker daemon")
    result = LocalDockerRouterConfigValidator(LocalDockerProvider(runner)).validate(image(), state)
    assert result.status == "unavailable" and len(runner.calls) == 1

def test_missing_docker_executable_is_unavailable(tmp_path):
    state = prepare_state(tmp_path)
    runner = FakeRunner(error=FileNotFoundError())
    result = LocalDockerRouterConfigValidator(LocalDockerProvider(runner)).validate(image(), state)
    assert result.status == "unavailable" and len(runner.calls) == 1
