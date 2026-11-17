"""Host-owned local Docker deployment provider.

Docker is invoked only through a fixed-argument subprocess boundary. This
module is not exposed as an Agent command and never uses a shell or sudo.
"""
from __future__ import annotations

import ipaddress
import json
import math
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
    DeploymentRuntimeInspection,
)

DEFAULT_DOCKER_TIMEOUT = 600.0
_OUTPUT_LIMIT = 4000
_PORT_MAPPING = re.compile(r"^(\d{1,5}):(\d{1,5})(?:/(tcp|udp))?$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")


def _is_allowlisted_haproxy_runtime_input(input_text: str) -> bool:
    """Defensive second-layer allowlist for the Router's privileged admin socket."""
    if not isinstance(input_text, str) or not input_text.endswith("\n"):
        return False
    if input_text.count("\n") != 1 or "\r" in input_text or "\x00" in input_text:
        return False
    line = input_text[:-1]
    identifier = r"[a-z][a-z0-9_-]{0,47}"
    map_path = r"/[a-zA-Z0-9_./-]{1,180}"
    map_reference = rf"(?:{map_path}|#[0-9]{{1,6}})"
    patterns = (
        r"show info",
        r"show map",
        r"show stat",
        rf"show stat {identifier} 4 -1",
        rf"show servers state(?: {identifier})?",
        rf"show servers conn(?: {identifier})?",
        rf"get map ({map_reference}) ({identifier})",
        rf"set map ({map_reference}) ({identifier}) (?:none|slot_a|slot_b)",
        rf"set server ({identifier})/({identifier}) addr ([0-9a-fA-F:.]+) port ([0-9]{{1,5}})",
        rf"set server ({identifier})/({identifier}) state (?:ready|drain|maint)",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, line)
        if match is None:
            continue
        if line.startswith(("get map ", "set map ")):
            reference = match.group(1)
            if reference.startswith("/") and any(
                part in {"", ".", ".."} for part in reference.split("/")[1:]
            ):
                return False
            if reference.startswith("#") and not re.fullmatch(r"#[0-9]{1,6}", reference):
                return False
        if line.startswith("set server ") and " addr " in line:
            try:
                ipaddress.ip_address(match.group(3))
                port = int(match.group(4))
            except (ValueError, TypeError):
                return False
            if not 1 <= port <= 65535:
                return False
        return True
    return False


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


class DockerCommandRunnerWithInput(Protocol):
    """Optional Host-only stdin capability; never exposed through Agent tools."""

    def execute_input(
        self, args: Sequence[str], *, input_text: str,
        cwd: str | None, timeout: float
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

    def execute_input(
        self, args: Sequence[str], *, input_text: str,
        cwd: str | None, timeout: float
    ) -> DockerCommandResult:
        """Execute fixed argv with bounded stdin; never invoke a shell."""
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(input_text, str) or "\x00" in input_text:
            raise ValueError("input_text must be a string without NUL bytes")
        if len(input_text.encode("utf-8")) > 65536:
            raise ValueError("Docker stdin payload exceeds 65536 UTF-8 bytes")
        completed = subprocess.run(
            [self.executable, *args],
            cwd=cwd,
            input=input_text,
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

    def execute_host_input(
        self, args: Sequence[str], *, input_text: str,
        cwd: str | None = None, timeout: float | None = None
    ) -> tuple[DockerCommandResult | None, str | None]:
        """Run a Host Docker operation with bounded stdin and fixed argv.

        The caller must build input_text through an allowlisted command builder.
        No shell or shell pipe is used.
        """
        if isinstance(args, (str, bytes)) or not isinstance(args, Sequence):
            raise ValueError("Docker args must be the exact HAProxy Unix socket exec argv")
        if any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in args):
            raise ValueError("Docker args must contain non-empty strings without NUL bytes")
        if (
            len(args) != 8
            or args[0] != "exec"
            or args[1] != "-i"
            or not re.fullmatch(r"[0-9a-f]{64}", args[2])
            or args[3] != "socat"
            or args[4] != "-T"
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", args[5])
            or not 0 < float(args[5]) <= 15
            or args[6] != "STDIO"
            or args[7] != "UNIX-CONNECT:/run/haproxy/admin.sock"
        ):
            raise ValueError("Docker stdin is restricted to Router immutable-ID Unix admin socket exec")
        if not isinstance(input_text, str) or "\x00" in input_text:
            raise ValueError("input_text must be a string without NUL bytes")
        if "\r" in input_text:
            raise ValueError("input_text must not contain carriage returns")
        if len(input_text.encode("utf-8")) > 1024:
            raise ValueError("HAProxy Runtime API input exceeds 1024 UTF-8 bytes")
        if not _is_allowlisted_haproxy_runtime_input(input_text):
            raise ValueError("input_text must be one allowlisted HAProxy Runtime API command line")
        effective_timeout = self.timeout if timeout is None else timeout
        if (
            not isinstance(effective_timeout, (int, float))
            or isinstance(effective_timeout, bool)
            or not math.isfinite(effective_timeout)
            or effective_timeout <= 0
        ):
            raise ValueError("timeout must be a finite positive number")
        executor = getattr(self.runner, "execute_input", None)
        if not callable(executor):
            return None, "configured Docker runner does not support stdin execution"
        try:
            result = executor(
                args, input_text=input_text, cwd=cwd,
                timeout=float(effective_timeout)
            )
        except FileNotFoundError:
            return None, "Docker executable not found"
        except subprocess.TimeoutExpired:
            return None, f"Docker command timed out after {effective_timeout:g} seconds"
        except OSError as exc:
            return None, f"Docker command could not start: {type(exc).__name__}"
        return result, None

    @staticmethod
    def _is_unavailable(message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in lowered
            for marker in (
                "docker executable not found",
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

        inspected, error = self._execute(
            ["inspect", "--format", "{{json .}}", deployment_id]
        )
        if error:
            return self._failure("deploy", error, output=f"container={deployment_id}")
        assert inspected is not None
        if inspected.returncode != 0:
            return self._failure(
                "deploy", "Container inspection failed after start",
                output=inspected.stderr or inspected.stdout,
            )
        try:
            container_state = json.loads(inspected.stdout)
        except (TypeError, json.JSONDecodeError):
            return self._failure(
                "deploy", "Docker returned malformed container inspection data",
                output=inspected.stdout,
            )
        if not isinstance(container_state, dict):
            return self._failure(
                "deploy", "Docker returned malformed container inspection data",
                output=inspected.stdout,
            )
        container_id = container_state.get("Id")
        state = container_state.get("State")
        if (
            not isinstance(container_id, str)
            or not _CONTAINER_ID.fullmatch(container_id)
            or not isinstance(state, dict)
            or state.get("Status") != "running"
        ):
            return self._failure(
                "deploy", "Container identity or running state could not be verified",
                output=inspected.stdout,
            )
        reported_id = result.stdout.strip()
        if not reported_id or not container_id.startswith(reported_id):
            return self._failure(
                "deploy", "Docker run identity does not match inspected immutable container ID",
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
            project=request.project,
            container_id=container_id,
        )
        return DeploymentOperationResult(
            "deploy", "succeeded", self.name, "Container started; health remains unverified",
            artifact=artifact, record=record,
            details={"container_id": container_id},
        )

    def health_check(self, record: DeploymentRecord) -> HealthCheckResult:
        if record.provider != self.name:
            return HealthCheckResult("unavailable", _now(), "docker inspect", "Record belongs to another provider")
        if record.container_id is None:
            return HealthCheckResult(
                "unknown", _now(), "docker inspect",
                "Historical record has no immutable container identity",
            )
        result, error = self._execute(
            ["inspect", "--format", "{{json .}}", record.deployment_id]
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
            inspected = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return HealthCheckResult("unknown", _now(), "docker inspect", "Docker returned invalid container inspection")
        if not isinstance(inspected, dict):
            return HealthCheckResult("unknown", _now(), "docker inspect", "Docker returned invalid container inspection")
        if inspected.get("Id") != record.container_id:
            return HealthCheckResult("unavailable", _now(), "docker inspect", "Container name resolves to a different immutable ID")
        state = inspected.get("State")
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

    def inspect_runtime(self, record: DeploymentRecord) -> DeploymentRuntimeInspection:
        """Inspect the immutable runtime ID persisted in a host deployment record."""
        if record.provider != self.name:
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=record.deployment_id,
                expected_runtime_id=record.container_id,
                observed_runtime_id=None,
                identity_match=False,
                status="invalid_response",
                runtime_state="unknown",
                health_status="unavailable",
                checked_at=_now(),
                probe="docker inspect by immutable container ID",
                detail="Record belongs to a different provider",
            )
        if record.container_id is None:
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=record.deployment_id,
                expected_runtime_id=None,
                observed_runtime_id=None,
                identity_match=False,
                status="invalid_response",
                runtime_state="unknown",
                health_status="unknown",
                checked_at=_now(),
                probe="docker inspect by immutable container ID",
                detail="Host history has no immutable container ID",
            )
        return self.inspect_runtime_identity(record.deployment_id, record.container_id)

    def inspect_runtime_identity(
        self,
        deployment_id: str,
        runtime_id: str,
    ) -> DeploymentRuntimeInspection:
        """Inspect a provider-issued immutable runtime ID without a history row.

        This is needed for crash recovery when a runtime ID reached the durable
        replacement journal but its DeploymentRecord has not yet been
        committed to host history. It never resolves a mutable container name.
        """
        if not isinstance(deployment_id, str) or not deployment_id.strip():
            raise ValueError("deployment_id must be a non-empty string")
        checked_at = _now()
        probe = "docker inspect by immutable container ID"
        if not isinstance(runtime_id, str) or not _CONTAINER_ID.fullmatch(runtime_id):
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=deployment_id,
                expected_runtime_id=None,
                observed_runtime_id=None,
                identity_match=False,
                status="invalid_response",
                runtime_state="unknown",
                health_status="unknown",
                checked_at=checked_at,
                probe=probe,
                detail="A full immutable Docker container ID is required",
            )

        expected_id = runtime_id
        inspect_format = (
            "{{.Id}}|{{.State.Status}}|"
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
        )
        result, error = self._execute(["inspect", "--format", inspect_format, expected_id])
        if error:
            lowered = error.lower()
            if "no such container" in lowered or "no such object" in lowered:
                status = "not_found"
                health = "unavailable"
            elif self._is_unavailable(error) or "timed out" in lowered:
                status = "unavailable"
                health = "unavailable"
            else:
                status = "invalid_response"
                health = "unknown"
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=deployment_id,
                expected_runtime_id=expected_id,
                observed_runtime_id=None,
                identity_match=False,
                status=status,
                runtime_state="unknown",
                health_status=health,
                checked_at=checked_at,
                probe=probe,
                detail=error,
            )

        assert result is not None
        output = result.stderr[-_OUTPUT_LIMIT:] or result.stdout[-_OUTPUT_LIMIT:]
        if result.returncode != 0:
            lowered = output.lower()
            if "no such container" in lowered or "no such object" in lowered:
                status = "not_found"
                health = "unavailable"
            elif self._is_unavailable(output):
                status = "unavailable"
                health = "unavailable"
            else:
                status = "invalid_response"
                health = "unknown"
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=deployment_id,
                expected_runtime_id=expected_id,
                observed_runtime_id=None,
                identity_match=False,
                status=status,
                runtime_state="unknown",
                health_status=health,
                checked_at=checked_at,
                probe=probe,
                detail=output or "Docker inspect failed",
            )

        fields = result.stdout.strip().split('|')
        if len(fields) != 3:
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=deployment_id,
                expected_runtime_id=expected_id,
                observed_runtime_id=None,
                identity_match=False,
                status="invalid_response",
                runtime_state="unknown",
                health_status="unknown",
                checked_at=checked_at,
                probe=probe,
                detail=(
                    "Docker returned malformed bounded container inspection data "
                    f"(exit={result.returncode}, fields={len(fields)}, "
                    f"stdout_chars={len(result.stdout)}, stderr_chars={len(result.stderr)})"
                ),
            )

        observed_id, raw_state, raw_health = fields
        if not isinstance(observed_id, str) or not _CONTAINER_ID.fullmatch(observed_id):
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=deployment_id,
                expected_runtime_id=expected_id,
                observed_runtime_id=None,
                identity_match=False,
                status="invalid_response",
                runtime_state="unknown",
                health_status="unknown",
                checked_at=checked_at,
                probe=probe,
                detail="Docker inspect did not return a valid immutable container ID",
            )
        if observed_id != expected_id:
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=deployment_id,
                expected_runtime_id=expected_id,
                observed_runtime_id=observed_id,
                identity_match=False,
                status="identity_mismatch",
                runtime_state="unknown",
                health_status="unavailable",
                checked_at=checked_at,
                probe=probe,
                detail="Docker inspect returned a different immutable container ID",
            )

        runtime_state = "unknown"
        health_status = "unknown"
        if raw_state in {
            "created", "running", "paused", "restarting",
            "removing", "exited", "dead",
        }:
            runtime_state = raw_state
            if runtime_state != "running":
                health_status = "unhealthy"
            elif raw_health == "healthy":
                health_status = "healthy"
            elif raw_health == "unhealthy":
                health_status = "unhealthy"
                        else:
                            health_status = "unknown"

        detail = ""
        if runtime_state == "unknown":
            detail = "Docker identity matched but runtime state is missing or unclassified"
        elif health_status == "unknown" and runtime_state == "running":
            detail = "Docker HEALTHCHECK is absent or has no terminal health state"
        elif health_status == "unhealthy":
            detail = f"Container runtime is {runtime_state}"

        return DeploymentRuntimeInspection(
            provider=self.name,
            deployment_id=deployment_id,
            expected_runtime_id=expected_id,
            observed_runtime_id=observed_id,
            identity_match=True,
            status="verified",
            runtime_state=runtime_state,
            health_status=health_status,
            checked_at=checked_at,
            probe=probe,
            detail=detail,
        )

    def stop(self, record: DeploymentRecord) -> DeploymentOperationResult:
        if record.provider != self.name:
            return self._failure("stop", "Record belongs to a different provider")
        if record.container_id is None:
            return self._failure("stop", "Record has no immutable container identity")
        inspected, error = self._execute(
            ["inspect", "--format", "{{json .}}", record.deployment_id]
        )
        if error:
            return self._failure("stop", error)
        assert inspected is not None
        if inspected.returncode != 0:
            return self._failure("stop", "Docker container identity inspection failed", output=inspected.stderr)
        try:
            current = json.loads(inspected.stdout)
        except (TypeError, json.JSONDecodeError):
            return self._failure("stop", "Docker returned malformed container inspection data")
        if not isinstance(current, dict) or current.get("Id") != record.container_id:
            return self._failure("stop", "Container name no longer resolves to the recorded immutable ID")
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
