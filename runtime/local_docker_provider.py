"""Host-owned local Docker deployment provider.

Docker is invoked only through a fixed-argument subprocess boundary. This
module is not exposed as an Agent command and never uses a shell or sudo.
"""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Sequence

from runtime.deployment_provider import (
    DeploymentArtifact,
    DeploymentOperationResult,
    DeploymentRecord,
    DeploymentRequest,
    HealthCheckResult,
)

DEFAULT_DOCKER_TIMEOUT = 600.0
_OUTPUT_LIMIT = 4000
_PORT_MAPPING = re.compile(r"^(\d{1,5}):(\d{1,5})(?:/(tcp|udp))?$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class DockerCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class DockerCommandRunner(Protocol):
    """Injectable host-side command boundary used by the provider."""

    def execute(
        self, args: Sequence[str], *, cwd: str | None, timeout: float
    ) -> DockerCommandResult: ...


class SubprocessDockerRunner:
    """Production runner: argv only, no shell, no implicit privilege escalation."""

    def __init__(self, executable: str = "docker") -> None:
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("docker executable must be a non-empty path")
        self.executable = executable

    def execute(
        self, args: Sequence[str], *, cwd: str | None, timeout: float
    ) -> DockerCommandResult:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        completed = subprocess.run(
            [self.executable, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
        return DockerCommandResult(
            completed.returncode,
            (completed.stdout or "")[-_OUTPUT_LIMIT:],
            (completed.stderr or "")[-_OUTPUT_LIMIT:],
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_component(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower()).strip("-.")
    if not result:
        raise ValueError("project/version must contain Docker-safe characters")
    return result[:48]


class LocalDockerProvider:
    """Build and run local containers without exposing Docker to Agents."""

    name = "docker-local"

    def __init__(
        self,
        runner: DockerCommandRunner | None = None,
        *,
        timeout: float = DEFAULT_DOCKER_TIMEOUT,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.runner = runner or SubprocessDockerRunner()
        self.timeout = timeout

    def _execute(
        self, args: Sequence[str], *, cwd: str | None = None
    ) -> tuple[DockerCommandResult | None, str | None]:
        try:
            result = self.runner.execute(args, cwd=cwd, timeout=self.timeout)
        except FileNotFoundError:
            return None, "Docker executable not found"
        except subprocess.TimeoutExpired:
            return None, f"Docker command timed out after {self.timeout:g} seconds"
        except OSError as exc:
            return None, f"Docker command could not start: {type(exc).__name__}"
        return result, None

    @staticmethod
    def _is_unavailable(message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in lowered
            for marker in (
                "cannot connect to the docker daemon",
                "is the docker daemon running",
                "error during connect",
                "daemon is not running",
                "connection refused",
            )
        )

    def _failure(
        self, operation: str, message: str, *, output: str = ""
    ) -> DeploymentOperationResult:
        status = "unavailable" if self._is_unavailable(message + " " + output) else "failed"
        return DeploymentOperationResult(
            operation, status, self.name, message,
            details={"output": output[-_OUTPUT_LIMIT:]} if output else {},
        )

    def build(self, request: DeploymentRequest) -> DeploymentOperationResult:
        root = Path(request.project_root).resolve()
        if not root.is_dir():
            return self._failure("build", "Project root is not a directory")
        if not (root / "Dockerfile").is_file():
            return self._failure("build", "Dockerfile is missing from project root")
        tag = (
            f"ai-team/{_safe_component(request.project)}:"
            f"{_safe_component(request.version)}"
        )
        result, error = self._execute(
            ["build", "--tag", tag, "--file", "Dockerfile", "."],
            cwd=str(root),
        )
        if error:
            return self._failure("build", error)
        assert result is not None
        if result.returncode != 0:
            return self._failure("build", "Docker image build failed", output=result.stderr or result.stdout)

        inspect, error = self._execute(
            ["image", "inspect", "--format", "{{.Id}}", tag]
        )
        if error:
            return self._failure("build", error)
        assert inspect is not None
        image_id = inspect.stdout.strip()
        if inspect.returncode != 0 or not _IMAGE_ID.fullmatch(image_id):
            return self._failure(
                "build", "Docker image inspection did not return a valid immutable image ID",
                output=inspect.stderr or inspect.stdout,
            )
        artifact = DeploymentArtifact(
            self.name, tag, image_id.removeprefix("sha256:"), request.version
        )
        return DeploymentOperationResult(
            "build", "succeeded", self.name, "Docker image built and identified",
            artifact=artifact, details={"image_id": image_id},
        )

    def deploy(
        self, request: DeploymentRequest, artifact: DeploymentArtifact
    ) -> DeploymentOperationResult:
        if artifact.provider != self.name:
            return self._failure("deploy", "Artifact belongs to a different provider")
        if not _IMAGE_ID.fullmatch("sha256:" + artifact.digest):
            return self._failure("deploy", "Artifact digest is invalid")
        inspect, error = self._execute(
            ["image", "inspect", "--format", "{{.Id}}", artifact.artifact_ref]
        )
        if error:
            return self._failure("deploy", error)
        assert inspect is not None
        if inspect.returncode != 0:
            return self._failure("deploy", "Built image is not available locally", output=inspect.stderr)
        if inspect.stdout.strip() != "sha256:" + artifact.digest:
            return self._failure("deploy", "Local image identity does not match artifact digest")

        for mapping in request.ports:
            match = _PORT_MAPPING.fullmatch(mapping)
            if not match or any(int(match.group(i)) > 65535 for i in (1, 2)) or any(
                int(match.group(i)) < 1 for i in (1, 2)
            ):
                return self._failure("deploy", f"Invalid port mapping: {mapping!r}")
        for key, value in request.labels.items():
            if any(ch in key + value for ch in ("\n", "\r", "\x00")):
                return self._failure("deploy", "Labels must not contain control characters")

        deployment_id = "ai-team-" + uuid.uuid4().hex[:16]
        args = ["run", "--detach", "--name", deployment_id]
        for key, value in sorted(request.labels.items()):
            args.extend(["--label", f"{key}={value}"])
        args.extend(["--label", f"ai-team.environment={request.environment}"])
        args.extend(["--label", f"ai-team.version={request.version}"])
        for mapping in request.ports:
            args.extend(["--publish", mapping])
        args.append(artifact.artifact_ref)
        result, error = self._execute(args)
        if error:
            return self._failure("deploy", error)
        assert result is not None
        if result.returncode != 0:
            return self._failure("deploy", "Docker container start failed", output=result.stderr or result.stdout)

        state, error = self._execute(
            ["inspect", "--format", "{{.State.Status}}", deployment_id]
        )
        if error:
            return self._failure("deploy", error, output=f"container={deployment_id}")
        assert state is not None
        if state.returncode != 0 or state.stdout.strip() != "running":
            return self._failure(
                "deploy", "Container did not enter running state",
                output=state.stderr or state.stdout,
            )
        record = DeploymentRecord(
            deployment_id=deployment_id,
            provider=self.name,
            environment=request.environment,
            version=request.version,
            artifact=artifact,
            status="running",
            health_status="unknown",
            created_at=_now(),
        )
        return DeploymentOperationResult(
            "deploy", "succeeded", self.name, "Container started; health remains unverified",
            artifact=artifact, record=record,
            details={"container_id": result.stdout.strip()},
        )

    def health_check(self, record: DeploymentRecord) -> HealthCheckResult:
        if record.provider != self.name:
            return HealthCheckResult("unavailable", _now(), "docker inspect", "Record belongs to another provider")
        result, error = self._execute(
            ["inspect", "--format", "{{json .State}}", record.deployment_id]
        )
        if error:
            status = "unavailable" if "not found" in error.lower() else "unknown"
            return HealthCheckResult(status, _now(), "docker inspect", error)
        assert result is not None
        if result.returncode != 0:
            message = result.stderr[-_OUTPUT_LIMIT:] or "Container inspection failed"
            status = "unavailable" if self._is_unavailable(message) else "unknown"
            return HealthCheckResult(status, _now(), "docker inspect", message)
        try:
            state = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return HealthCheckResult("unknown", _now(), "docker inspect", "Docker returned invalid container state")
        if not isinstance(state, dict) or state.get("Status") != "running":
            return HealthCheckResult("unhealthy", _now(), "docker inspect", "Container is not running")
        health = state.get("Health")
        if not isinstance(health, dict):
            return HealthCheckResult("unknown", _now(), "docker healthcheck", "Image defines no Docker HEALTHCHECK")
        docker_status = health.get("Status")
        if docker_status == "healthy":
            return HealthCheckResult("healthy", _now(), "docker healthcheck")
        if docker_status == "unhealthy":
            return HealthCheckResult("unhealthy", _now(), "docker healthcheck", "Docker healthcheck reports unhealthy")
        return HealthCheckResult("unknown", _now(), "docker healthcheck", f"Health state: {docker_status!r}")

    def stop(self, record: DeploymentRecord) -> DeploymentOperationResult:
        if record.provider != self.name:
            return self._failure("stop", "Record belongs to a different provider")
        result, error = self._execute(["stop", "--time", "10", record.deployment_id])
        if error:
            return self._failure("stop", error)
        assert result is not None
        if result.returncode != 0:
            return self._failure("stop", "Docker container stop failed", output=result.stderr)
        return DeploymentOperationResult(
            "stop", "succeeded", self.name, "Container stopped",
            artifact=record.artifact, record=record,
        )

    def rollback(
        self, request: DeploymentRequest, previous: DeploymentRecord
    ) -> DeploymentOperationResult:
        return DeploymentOperationResult(
            "rollback", "unsupported", self.name,
            "Rollback requires host-owned deployment history and is implemented in the next milestone",
        )
