"""Build and verify the pinned Router image, returning only immutable identity.

Build uses a fixed Dockerfile and minimal context. Verification inspects the
image configuration and runs a disposable, network-isolated, read-only
container by immutable image ID. It never starts the persistent Router.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from runtime.local_docker_provider import LocalDockerProvider

ROUTER_IMAGE_TAG = "ai-team/router:contract-1"
ROUTER_IMAGE_CONTEXT = Path("docker") / "router"
ROUTER_BASE_IMAGE_REF = (
    "haproxytech/haproxy-alpine@sha256:"
    "c9d745967c0651adbfdf0150a739a833a790f3b4eced1758374a6b0f3820c8d9"
)
ROUTER_HAPROXY_VERSION = "3.4.7"
ROUTER_SOCAT_PACKAGE_VERSION = "1.8.1.3-r0"
ROUTER_IMAGE_CONTRACT_VERSION = "1"
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_SUPPORTED_ARCHITECTURES = frozenset({"amd64", "arm64"})
_VERIFY_SCRIPT = "\n".join((
    "set -eu",
    "command -v haproxy >/dev/null",
    "command -v socat >/dev/null",
    'haproxy -vv | grep -F "HAProxy version 3.4.7" >/dev/null',
    'socat -V | grep -F "socat version 1.8.1.3" >/dev/null',
    'apk info -v | grep -Fx "socat-1.8.1.3-r0" >/dev/null',
))

ImageStatus = Literal["verified", "unavailable", "failed", "mismatch", "invalid_response"]


@dataclass(frozen=True)
class DockerRouterImageIdentity:
    """Verified local Router image identity; use image_id, never its build tag."""

    image_id: str
    operating_system: str
    architecture: str
    haproxy_version: str
    socat_package_version: str
    base_image_ref: str
    contract_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.image_id, str) or not _IMAGE_ID.fullmatch(self.image_id):
            raise ValueError("image_id must be a full immutable Docker SHA-256 image ID")
        if self.operating_system != "linux":
            raise ValueError("Router image OS must be linux")
        if self.architecture not in _SUPPORTED_ARCHITECTURES:
            raise ValueError("Router image architecture must be amd64 or arm64")
        if self.haproxy_version != ROUTER_HAPROXY_VERSION:
            raise ValueError("Router image HAProxy version does not match the pinned contract")
        if self.socat_package_version != ROUTER_SOCAT_PACKAGE_VERSION:
            raise ValueError("Router image socat package version does not match the pinned contract")
        if self.base_image_ref != ROUTER_BASE_IMAGE_REF:
            raise ValueError("Router image base reference does not match the pinned digest")
        if self.contract_version != ROUTER_IMAGE_CONTRACT_VERSION:
            raise ValueError("Router image contract version is unsupported")


@dataclass(frozen=True)
class DockerRouterImageResult:
    status: ImageStatus
    identity: DockerRouterImageIdentity | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"verified", "unavailable", "failed", "mismatch", "invalid_response"}:
            raise ValueError("invalid Router image result status")
        if self.status == "verified":
            if not isinstance(self.identity, DockerRouterImageIdentity):
                raise ValueError("verified Router image result requires an immutable identity")
        elif self.identity is not None:
            raise ValueError("unverified Router image result must not expose a trusted identity")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


class LocalDockerRouterImageManager:
    """Build the checked-in Router image and verify it using its immutable ID."""

    def __init__(self, provider: LocalDockerProvider, repository_root: str | Path) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        if not isinstance(repository_root, (str, Path)) or not str(repository_root).strip():
            raise TypeError("repository_root must be a non-empty path")
        self.provider = provider
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.build_context = self.repository_root / ROUTER_IMAGE_CONTEXT

    def _unavailable(self, detail: str) -> DockerRouterImageResult:
        return DockerRouterImageResult("unavailable", detail=detail)

    def _command_failure(self, detail: str) -> DockerRouterImageResult:
        status = "unavailable" if self.provider._is_unavailable(detail) else "failed"
        return DockerRouterImageResult(status, detail=detail[:1000])

    @staticmethod
    def _inspect_identity(payload: object) -> tuple[DockerRouterImageIdentity | None, str]:
        if not isinstance(payload, dict):
            return None, "Docker image inspect response must be one JSON object"
        image_id = payload.get("Id")
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            return None, "Docker image inspect did not return a full immutable image ID"
        config = payload.get("Config")
        if not isinstance(config, dict):
            return None, "Docker image inspect Config is missing or malformed"
        labels = config.get("Labels")
        if not isinstance(labels, dict):
            return None, "Docker image inspect labels are missing or malformed"
        expected_labels = {
            "com.ai-team.router.image-contract": ROUTER_IMAGE_CONTRACT_VERSION,
            "com.ai-team.router.haproxy-version": ROUTER_HAPROXY_VERSION,
            "com.ai-team.router.socat-package-version": ROUTER_SOCAT_PACKAGE_VERSION,
            "com.ai-team.router.base-image": ROUTER_BASE_IMAGE_REF,
        }
        if any(labels.get(key) != value for key, value in expected_labels.items()):
            return None, "Docker image labels do not match the pinned Router image contract"
        if config.get("Entrypoint") != ["/docker-entrypoint.sh"]:
            return None, "Router image entrypoint does not match the reviewed HAProxy base contract"
        if config.get("Cmd") != ["haproxy", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]:
            return None, "Router image command does not match the reviewed HAProxy base contract"
        operating_system = payload.get("Os")
        architecture = payload.get("Architecture")
        if operating_system != "linux" or architecture not in _SUPPORTED_ARCHITECTURES:
            return None, "Router image platform must be linux/amd64 or linux/arm64"
        return DockerRouterImageIdentity(
            image_id=image_id,
            operating_system=operating_system,
            architecture=architecture,
            haproxy_version=ROUTER_HAPROXY_VERSION,
            socat_package_version=ROUTER_SOCAT_PACKAGE_VERSION,
            base_image_ref=ROUTER_BASE_IMAGE_REF,
            contract_version=ROUTER_IMAGE_CONTRACT_VERSION,
        ), ""

    def inspect_image(self, image_id: str) -> DockerRouterImageResult:
        """Verify an existing immutable image by ID without building or running it."""
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            return DockerRouterImageResult(
                "invalid_response",
                detail="Existing Router image inspection requires a full immutable SHA-256 image ID",
            )
        inspect, error = self.provider._execute(
            ["image", "inspect", "--format", "{{json .}}", image_id]
        )
        if error:
            return self._command_failure(error)
        assert inspect is not None
        if inspect.returncode != 0:
            message = inspect.stderr or inspect.stdout or "Immutable Router image is unavailable"
            status = "unavailable" if self.provider._is_unavailable(message) else "failed"
            return DockerRouterImageResult(status, detail=message[:1000])
        try:
            payload = json.loads(inspect.stdout)
        except (TypeError, json.JSONDecodeError):
            return DockerRouterImageResult(
                "invalid_response", detail="Docker immutable image inspect returned malformed JSON"
            )
        identity, mismatch = self._inspect_identity(payload)
        if identity is None:
            status = (
                "invalid_response"
                if "JSON object" in mismatch or "malformed" in mismatch or "immutable image ID" in mismatch
                else "mismatch"
            )
            return DockerRouterImageResult(status, detail=mismatch)
        if identity.image_id != image_id:
            return DockerRouterImageResult(
                "mismatch", detail="Docker image inspect returned a different immutable image ID"
            )
        return DockerRouterImageResult(
            "verified", identity, "Existing immutable Router image matches the pinned metadata contract"
        )

    def build_and_verify(self) -> DockerRouterImageResult:
        """Build fixed recipe, inspect the image, then verify by immutable ID.

        The temporary verification container is network-none, read-only,
        capability-free and removed on exit. No published port or volume is used.
        """
        dockerfile = self.build_context / "Dockerfile"
        if not self.build_context.is_dir() or not dockerfile.is_file():
            return DockerRouterImageResult(
                "failed", detail="Pinned Router Dockerfile or minimal build context is missing"
            )
        build, error = self.provider._execute(
            ["build", "--pull", "--file", "Dockerfile", "--tag", ROUTER_IMAGE_TAG, "."],
            cwd=str(self.build_context),
        )
        if error:
            return self._command_failure(error)
        assert build is not None
        if build.returncode != 0:
            return self._command_failure("Pinned Router image build failed: " + (build.stderr or build.stdout))

        inspect, error = self.provider._execute(
            ["image", "inspect", "--format", "{{json .}}", ROUTER_IMAGE_TAG]
        )
        if error:
            return self._command_failure(error)
        assert inspect is not None
        if inspect.returncode != 0:
            return self._command_failure("Pinned Router image inspect failed: " + (inspect.stderr or inspect.stdout))
        try:
            payload = json.loads(inspect.stdout)
        except (TypeError, json.JSONDecodeError):
            return DockerRouterImageResult("invalid_response", detail="Docker image inspect returned malformed JSON")
        identity, mismatch = self._inspect_identity(payload)
        if identity is None:
            status = "invalid_response" if "JSON object" in mismatch or "malformed" in mismatch or "immutable image ID" in mismatch else "mismatch"
            return DockerRouterImageResult(status, detail=mismatch)

        verify, error = self.provider._execute([
            "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--entrypoint", "/bin/sh",
            identity.image_id, "-ec", _VERIFY_SCRIPT,
        ])
        if error:
            return self._command_failure(error)
        assert verify is not None
        if verify.returncode != 0:
            message = verify.stderr or verify.stdout or "Router image runtime binary verification failed"
            status = "unavailable" if self.provider._is_unavailable(message) else "mismatch"
            return DockerRouterImageResult(status, detail=message[:1000])
        return DockerRouterImageResult("verified", identity, "Pinned Router image built and verified by immutable image ID")
