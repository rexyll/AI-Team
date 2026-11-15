from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime.deployment_provider import DeploymentArtifact, DeploymentRecord, DeploymentRequest
from runtime.local_docker_provider import (
    DockerCommandResult, LocalDockerProvider, SubprocessDockerRunner,
)


class FakeRunner:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append((list(args), cwd, timeout))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def request(root: Path) -> DeploymentRequest:
    return DeploymentRequest(str(root), "demo app", "local", "1.2.3", ("8080:80",), {"team": "qa"})


def artifact() -> DeploymentArtifact:
    return DeploymentArtifact("docker-local", "ai-team/demo-app:1.2.3", "a" * 64, "1.2.3")


def record() -> DeploymentRecord:
    return DeploymentRecord(
        "ai-team-container", "docker-local", "local", "1.2.3", artifact(),
        "running", "unknown", "2026-11-15T10:00:00Z",
    )


def ok(stdout="", stderr=""):
    return DockerCommandResult(0, stdout, stderr)


def failed(stderr="build failed"):
    return DockerCommandResult(1, "", stderr)


def test_docker_runner_uses_argv_without_shell(monkeypatch):
    observed = {}

    def fake_run(args, **kwargs):
        observed["args"] = args
        observed.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = SubprocessDockerRunner("/opt/docker").execute(["version"], cwd=None, timeout=3)

    assert result.stdout == "ok"
    assert observed["args"] == ["/opt/docker", "version"]
    assert observed["shell"] is False
    assert observed["timeout"] == 3


def test_missing_docker_executable_is_unavailable(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
    provider = LocalDockerProvider(FakeRunner(FileNotFoundError()), timeout=2)

    result = provider.build(request(tmp_path))

    assert result.status == "unavailable"
    assert "not found" in result.message.lower()


def test_daemon_unavailable_is_not_reported_as_success(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
    runner = FakeRunner(failed("Cannot connect to the Docker daemon"))
    result = LocalDockerProvider(runner).build(request(tmp_path))
    assert result.status == "unavailable"


def test_build_failure_is_reported(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
    result = LocalDockerProvider(FakeRunner(failed("invalid Dockerfile"))).build(request(tmp_path))
    assert result.status == "failed"
    assert "build failed" in result.message.lower()


def test_build_returns_verified_immutable_image_id(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
    image_id = "sha256:" + "b" * 64
    runner = FakeRunner(ok("Successfully built"), ok(image_id + "\n"))
    result = LocalDockerProvider(runner).build(request(tmp_path))
    assert result.status == "succeeded"
    assert result.artifact.digest == "b" * 64
    assert result.details["image_id"] == image_id
    assert runner.calls[0][0][:3] == ["build", "--tag", "ai-team/demo-app:1.2.3"]


def test_build_rejects_missing_dockerfile(tmp_path):
    result = LocalDockerProvider(FakeRunner()).build(request(tmp_path))
    assert result.status == "failed"
    assert "Dockerfile" in result.message


def test_deploy_rejects_digest_mismatch_before_starting():
    runner = FakeRunner(ok("sha256:" + "c" * 64))
    result = LocalDockerProvider(runner).deploy(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3"), artifact()
    )
    assert result.status == "failed"
    assert "identity" in result.message
    assert len(runner.calls) == 1


def test_container_start_failure_is_reported():
    runner = FakeRunner(ok("sha256:" + "a" * 64), failed("port is already allocated"))
    result = LocalDockerProvider(runner).deploy(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3"), artifact()
    )
    assert result.status == "failed"
    assert "start failed" in result.message.lower()


def test_deploy_requires_running_container_and_keeps_health_unknown():
    runner = FakeRunner(
        ok("sha256:" + "a" * 64), ok("container-id\n"), ok("running\n")
    )
    result = LocalDockerProvider(runner).deploy(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3", ("8080:80",)), artifact()
    )
    assert result.status == "succeeded"
    assert result.record.status == "running"
    assert result.record.health_status == "unknown"
    assert result.details["container_id"] == "container-id"


@pytest.mark.parametrize("state,expected", [
    ({"Status": "running"}, "unknown"),
    ({"Status": "running", "Health": {"Status": "healthy"}}, "healthy"),
    ({"Status": "running", "Health": {"Status": "unhealthy"}}, "unhealthy"),
    ({"Status": "exited"}, "unhealthy"),
])
def test_health_check_never_assumes_missing_health_is_healthy(state, expected):
    runner = FakeRunner(ok(json.dumps(state)))
    result = LocalDockerProvider(runner).health_check(record())
    assert result.status == expected


def test_stop_reports_docker_failure():
    result = LocalDockerProvider(FakeRunner(failed("no such container"))).stop(record())
    assert result.status == "failed"


def test_rollback_is_explicitly_unsupported_until_host_history_exists():
    result = LocalDockerProvider(FakeRunner()).rollback(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3"), record()
    )
    assert result.status == "unsupported"
