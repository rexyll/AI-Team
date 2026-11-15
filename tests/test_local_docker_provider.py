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
        "running", "unknown", "2026-11-15T10:00:00Z", container_id="f" * 64,
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
        ok("sha256:" + "a" * 64), ok("d" * 64 + "\n"), ok(json.dumps({"Id": "d" * 64, "State": {"Status": "running"}}))
    )
    result = LocalDockerProvider(runner).deploy(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3", ("8080:80",)), artifact()
    )
    assert result.status == "succeeded"
    assert result.record.status == "running"
    assert result.record.health_status == "unknown"
    assert result.record.container_id == "d" * 64
    assert result.details["container_id"] == "d" * 64


def test_deploy_rejects_malformed_container_inspection():
    runner = FakeRunner(
        ok("sha256:" + "a" * 64), ok("d" * 64 + "\n"), ok("not-json")
    )
    result = LocalDockerProvider(runner).deploy(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3"), artifact()
    )
    assert result.status == "failed"
    assert "malformed" in result.message.lower()


def test_deploy_rejects_container_id_mismatch():
    runner = FakeRunner(
        ok("sha256:" + "a" * 64), ok("d" * 64 + "\n"),
        ok(json.dumps({"Id": "e" * 64, "State": {"Status": "running"}})),
    )
    result = LocalDockerProvider(runner).deploy(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3"), artifact()
    )
    assert result.status == "failed"
    assert "identity" in result.message.lower()


@pytest.mark.parametrize("state,expected", [
    ({"Status": "running"}, "unknown"),
    ({"Status": "running", "Health": {"Status": "healthy"}}, "healthy"),
    ({"Status": "running", "Health": {"Status": "unhealthy"}}, "unhealthy"),
    ({"Status": "exited"}, "unhealthy"),
])
def test_health_check_never_assumes_missing_health_is_healthy(state, expected):
    runner = FakeRunner(ok(json.dumps({"Id": "f" * 64, "State": state})))
    result = LocalDockerProvider(runner).health_check(record())
    assert result.status == expected


def test_stop_reports_docker_failure():
    runner = FakeRunner(ok(json.dumps({"Id": "f" * 64})), failed("no such container"))
    result = LocalDockerProvider(runner).stop(record())
    assert result.status == "failed"


def test_health_check_rejects_reused_container_name():
    runner = FakeRunner(ok(json.dumps({
        "Id": "e" * 64, "State": {"Status": "running", "Health": {"Status": "healthy"}}
    })))
    result = LocalDockerProvider(runner).health_check(record())
    assert result.status == "unavailable"
    assert "different immutable id" in result.detail.lower()


def test_stop_refuses_reused_container_name():
    runner = FakeRunner(ok(json.dumps({"Id": "e" * 64})))
    result = LocalDockerProvider(runner).stop(record())
    assert result.status == "failed"
    assert "immutable id" in result.message.lower()
    assert len(runner.calls) == 1


def test_rollback_is_explicitly_unsupported_until_host_history_exists():
    result = LocalDockerProvider(FakeRunner()).rollback(
        DeploymentRequest("/tmp", "demo", "local", "1.2.3"), record()
    )
    assert result.status == "unsupported"


def test_inspect_runtime_uses_immutable_container_id_not_mutable_name():
    expected_id = "f" * 64
    runner = FakeRunner(ok(json.dumps({
        "Id": expected_id,
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
    })))

    result = LocalDockerProvider(runner).inspect_runtime(record())

    assert result.status == "verified"
    assert result.identity_match is True
    assert result.expected_runtime_id == expected_id
    assert result.observed_runtime_id == expected_id
    assert result.runtime_state == "running"
    assert result.health_status == "healthy"
    assert runner.calls[0][0] == ["inspect", "--format", "{{json .}}", expected_id]


def test_inspect_runtime_reports_identity_mismatch_without_trusting_name():
    runner = FakeRunner(ok(json.dumps({
        "Id": "e" * 64,
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
    })))

    result = LocalDockerProvider(runner).inspect_runtime(record())

    assert result.status == "identity_mismatch"
    assert result.identity_match is False
    assert result.expected_runtime_id == "f" * 64
    assert result.observed_runtime_id == "e" * 64
    assert result.health_status == "unavailable"
    assert runner.calls[0][0][-1] == "f" * 64


@pytest.mark.parametrize(
    ("state", "expected_health"),
    [
        ({"Status": "exited"}, "unhealthy"),
        ({"Status": "paused"}, "unhealthy"),
        ({"Status": "running"}, "unknown"),
        ({"Status": "running", "Health": {"Status": "starting"}}, "unknown"),
        ({"Status": "running", "Health": {"Status": "unhealthy"}}, "unhealthy"),
    ],
)
def test_inspect_runtime_keeps_lifecycle_and_health_separate(state, expected_health):
    runner = FakeRunner(ok(json.dumps({"Id": "f" * 64, "State": state})))

    result = LocalDockerProvider(runner).inspect_runtime(record())

    assert result.status == "verified"
    assert result.identity_match is True
    assert result.health_status == expected_health


def test_inspect_runtime_identity_supports_journal_id_without_history_record():
    runtime_id = "f" * 64
    runner = FakeRunner(ok(json.dumps({
        "Id": runtime_id,
        "State": {"Status": "running", "Health": {"Status": "starting"}},
    })))

    result = LocalDockerProvider(runner).inspect_runtime_identity(
        "journal-candidate", runtime_id
    )

    assert result.status == "verified"
    assert result.deployment_id == "journal-candidate"
    assert result.expected_runtime_id == runtime_id
    assert result.health_status == "unknown"
    assert runner.calls[0][0] == ["inspect", "--format", "{{json .}}", runtime_id]


def test_inspect_runtime_identity_rejects_invalid_id_without_docker_call():
    runner = FakeRunner()

    result = LocalDockerProvider(runner).inspect_runtime_identity(
        "journal-candidate", "candidate-container-name"
    )

    assert result.status == "invalid_response"
    assert result.expected_runtime_id is None
    assert runner.calls == []


def test_inspect_runtime_reports_missing_container_by_immutable_id():
    runner = FakeRunner(failed("Error: No such object: " + "f" * 64))

    result = LocalDockerProvider(runner).inspect_runtime(record())

    assert result.status == "not_found"
    assert result.observed_runtime_id is None
    assert runner.calls[0][0][-1] == "f" * 64


def test_inspect_runtime_reports_daemon_unavailable():
    runner = FakeRunner(failed("Cannot connect to the Docker daemon"))

    result = LocalDockerProvider(runner).inspect_runtime(record())

    assert result.status == "unavailable"
    assert result.health_status == "unavailable"


def test_inspect_runtime_rejects_malformed_json():
    runner = FakeRunner(ok("not-json"))

    result = LocalDockerProvider(runner).inspect_runtime(record())

    assert result.status == "invalid_response"
    assert result.identity_match is False


def test_inspect_runtime_does_not_call_docker_without_immutable_id():
    original = record()
    legacy = DeploymentRecord(
        original.deployment_id,
        original.provider,
        original.environment,
        original.version,
        original.artifact,
        original.status,
        original.health_status,
        original.created_at,
        project=original.project,
    )
    runner = FakeRunner()

    result = LocalDockerProvider(runner).inspect_runtime(legacy)

    assert result.status == "invalid_response"
    assert result.expected_runtime_id is None
    assert "immutable" in result.detail.lower()
    assert runner.calls == []


def test_inspect_runtime_rejects_foreign_provider_before_docker_call():
    original = record()
    foreign_artifact = DeploymentArtifact(
        "foreign", "image:foreign", "b" * 64, "1.2.3"
    )
    foreign = DeploymentRecord(
        "foreign-container",
        "foreign",
        original.environment,
        original.version,
        foreign_artifact,
        original.status,
        original.health_status,
        original.created_at,
        project=original.project,
        container_id=original.container_id,
    )
    runner = FakeRunner()

    result = LocalDockerProvider(runner).inspect_runtime(foreign)

    assert result.status == "invalid_response"
    assert "different provider" in result.detail.lower()
    assert runner.calls == []


def test_runtime_inspection_contract_rejects_false_identity_claims():
    from runtime.deployment_provider import DeploymentRuntimeInspection

    with pytest.raises(ValueError, match="match"):
        DeploymentRuntimeInspection(
            provider="docker-local",
            deployment_id="release",
            expected_runtime_id="f" * 64,
            observed_runtime_id="e" * 64,
            identity_match=True,
            status="verified",
            runtime_state="running",
            health_status="healthy",
            checked_at="2026-11-15T16:00:00Z",
            probe="test",
        )

    with pytest.raises(ValueError, match="healthy"):
        DeploymentRuntimeInspection(
            provider="docker-local",
            deployment_id="release",
            expected_runtime_id="f" * 64,
            observed_runtime_id=None,
            identity_match=False,
            status="not_found",
            runtime_state="unknown",
            health_status="healthy",
            checked_at="2026-11-15T16:00:00Z",
            probe="test",
        )


def test_inspect_runtime_treats_unclassified_state_payload_as_unknown():
    runner = FakeRunner(ok(json.dumps({
        "Id": "f" * 64,
        "State": {"Status": ["unexpected"]},
    })))

    result = LocalDockerProvider(runner).inspect_runtime(record())

    assert result.status == "verified"
    assert result.runtime_state == "unknown"
    assert result.health_status == "unknown"


def test_runtime_inspection_rejects_non_immutable_expected_ids():
    from runtime.deployment_provider import DeploymentRuntimeInspection

    with pytest.raises(ValueError, match="full lowercase immutable"):
        DeploymentRuntimeInspection(
            provider="docker-local",
            deployment_id="release",
            expected_runtime_id="container-name",
            observed_runtime_id=None,
            identity_match=False,
            status="not_found",
            runtime_state="unknown",
            health_status="unavailable",
            checked_at="2026-11-15T16:00:00Z",
            probe="test",
        )
