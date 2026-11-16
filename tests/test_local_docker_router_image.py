from __future__ import annotations

import json

import pytest

from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.local_docker_router_image import (
    ROUTER_BASE_IMAGE_REF,
    ROUTER_HAPROXY_VERSION,
    ROUTER_IMAGE_TAG,
    ROUTER_SOCAT_PACKAGE_VERSION,
    LocalDockerRouterImageManager,
)


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


def inspect_payload(**overrides):
    payload = {
        "Id": "sha256:" + "a" * 64,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Labels": {
                "com.ai-team.router.image-contract": "1",
                "com.ai-team.router.haproxy-version": ROUTER_HAPROXY_VERSION,
                "com.ai-team.router.socat-package-version": ROUTER_SOCAT_PACKAGE_VERSION,
                "com.ai-team.router.base-image": ROUTER_BASE_IMAGE_REF,
            },
            "Entrypoint": ["/docker-entrypoint.sh"],
            "Cmd": ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"],
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


def make_manager(tmp_path, *results):
    context = tmp_path / "docker" / "router"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text("FROM pinned-image\n", encoding="utf-8")
    runner = FakeRunner(*results)
    return LocalDockerRouterImageManager(LocalDockerProvider(runner), tmp_path), runner, context


def test_builds_then_inspects_and_runs_only_by_immutable_image_id(tmp_path):
    manager, runner, context = make_manager(tmp_path, ok(), ok(inspect_payload()), ok("verified"))

    result = manager.build_and_verify()

    assert result.status == "verified"
    assert result.identity.image_id == "sha256:" + "a" * 64
    assert result.identity.architecture == "amd64"
    assert runner.calls[0][0] == [
        "build", "--pull", "--file", "Dockerfile", "--tag", ROUTER_IMAGE_TAG, ".",
    ]
    assert runner.calls[0][1] == str(context)
    assert runner.calls[1][0] == [
        "image", "inspect", "--format", "{{json .}}", ROUTER_IMAGE_TAG,
    ]
    verify_args = runner.calls[2][0]
    assert verify_args[:9] == [
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
    ]
    assert verify_args[9:12] == ["--entrypoint", "/bin/sh", "sha256:" + "a" * 64]
    assert verify_args[-2] == "-ec"
    assert "socat version 1.8.1.3" in verify_args[-1]
    assert "socat-1.8.1.3-r0" in verify_args[-1]
    assert all("--publish" not in args and "--privileged" not in args for args, _, _ in runner.calls)


def test_missing_router_dockerfile_fails_without_docker_side_effect(tmp_path):
    runner = FakeRunner()
    manager = LocalDockerRouterImageManager(LocalDockerProvider(runner), tmp_path)
    result = manager.build_and_verify()
    assert result.status == "failed"
    assert runner.calls == []


def test_docker_executable_missing_is_unavailable(tmp_path):
    manager, runner, _ = make_manager(tmp_path, FileNotFoundError())
    result = manager.build_and_verify()
    assert result.status == "unavailable"
    assert len(runner.calls) == 1


def test_failed_image_build_does_not_inspect_or_run(tmp_path):
    manager, runner, _ = make_manager(tmp_path, failed("Docker build failed"))
    result = manager.build_and_verify()
    assert result.status == "failed"
    assert len(runner.calls) == 1


@pytest.mark.parametrize("inspect_output", ["{broken", "[]", json.dumps({"Id": "mutable-tag"})])
def test_malformed_or_non_immutable_inspect_response_is_rejected(tmp_path, inspect_output):
    manager, runner, _ = make_manager(tmp_path, ok(), ok(inspect_output))
    result = manager.build_and_verify()
    assert result.status == "invalid_response"
    assert result.identity is None
    assert len(runner.calls) == 2


@pytest.mark.parametrize("overrides", [
    {"Os": "windows"},
    {"Architecture": "386"},
    {"Config": {"Labels": {}, "Entrypoint": ["/docker-entrypoint.sh"], "Cmd": ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]}},
    {"Config": {"Labels": {"com.ai-team.router.image-contract": "1"}, "Entrypoint": ["/docker-entrypoint.sh"], "Cmd": ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]}},
    {"Config": {"Labels": {
        "com.ai-team.router.image-contract": "1",
        "com.ai-team.router.haproxy-version": ROUTER_HAPROXY_VERSION,
        "com.ai-team.router.socat-package-version": ROUTER_SOCAT_PACKAGE_VERSION,
        "com.ai-team.router.base-image": ROUTER_BASE_IMAGE_REF,
    }, "Entrypoint": ["/bin/sh"], "Cmd": ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]}},
])
def test_image_config_mismatch_fails_closed_without_running_verification(tmp_path, overrides):
    manager, runner, _ = make_manager(tmp_path, ok(), ok(inspect_payload(**overrides)))
    result = manager.build_and_verify()
    assert result.status == "mismatch"
    assert result.identity is None
    assert len(runner.calls) == 2


def test_runtime_binary_verification_failure_does_not_return_identity(tmp_path):
    manager, runner, _ = make_manager(tmp_path, ok(), ok(inspect_payload()), failed("socat missing"))
    result = manager.build_and_verify()
    assert result.status == "mismatch"
    assert result.identity is None
    assert runner.calls[2][0][9:12] == ["--entrypoint", "/bin/sh", "sha256:" + "a" * 64]


def test_unavailable_docker_daemon_during_verification_remains_unavailable(tmp_path):
    manager, runner, _ = make_manager(tmp_path, ok(), ok(inspect_payload()), failed("Cannot connect to the Docker daemon"))
    result = manager.build_and_verify()
    assert result.status == "unavailable"


def test_manager_requires_local_docker_provider(tmp_path):
    with pytest.raises(TypeError, match="LocalDockerProvider"):
        LocalDockerRouterImageManager(object(), tmp_path)

