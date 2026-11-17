"""Idempotent Host manager for creating and verifying the persistent Router container.

Only a previously validated DockerRouterContainerSpec is executable. The manager
never removes, stops, restarts, or repairs an existing mismatched container.
Every create attempt is followed by an immutable inspect read-back.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_container import (
    DockerRouterContainerSpec,
    verify_router_container_inspection,
)

RouterEnsureStatus = Literal[
    "created", "existing", "unavailable", "failed", "mismatch", "invalid_response"
]
_MISSING_MARKERS = ("no such object", "no such container")
# Keep the inspect payload below LocalDockerProvider's bounded 4 KiB output
# ceiling. The full Docker object can be much larger and would be truncated,
# making a valid identity appear malformed. Every field consumed by
# verify_router_container_inspection is retained in this compact JSON view.
ROUTER_CONTAINER_INSPECT_FORMAT = r'{{printf "{\"Id\":%q,\"Name\":%q,\"Config\":{\"Image\":%q,\"User\":%q,\"Entrypoint\":%s,\"Cmd\":%s,\"Labels\":%s},\"State\":{\"Running\":%t},\"HostConfig\":{\"ReadonlyRootfs\":%t,\"Privileged\":%t,\"CapDrop\":%s,\"CapAdd\":%s,\"SecurityOpt\":%s,\"NetworkMode\":%q,\"RestartPolicy\":{\"Name\":%q},\"Tmpfs\":%s,\"PortBindings\":%s},\"Mounts\":%s,\"NetworkSettings\":{\"Networks\":%s,\"Ports\":%s}}" .Id .Name .Config.Image .Config.User (json .Config.Entrypoint) (json .Config.Cmd) (json .Config.Labels) .State.Running .HostConfig.ReadonlyRootfs .HostConfig.Privileged (json .HostConfig.CapDrop) (json .HostConfig.CapAdd) (json .HostConfig.SecurityOpt) .HostConfig.NetworkMode .HostConfig.RestartPolicy.Name (json .HostConfig.Tmpfs) (json .HostConfig.PortBindings) (json .Mounts) (json .NetworkSettings.Networks) (json .NetworkSettings.Ports)}}'


@dataclass(frozen=True)
class DockerRouterContainerEnsureResult:
    status: RouterEnsureStatus
    container_id: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {
            "created", "existing", "unavailable", "failed", "mismatch", "invalid_response"
        }:
            raise ValueError("invalid Router container ensure status")
        if self.status in {"created", "existing"}:
            if not isinstance(self.container_id, str) or len(self.container_id) != 64 or any(
                ch not in "0123456789abcdef" for ch in self.container_id
            ):
                raise ValueError("verified Router results require a full immutable container ID")
        elif self.container_id is not None:
            raise ValueError("unverified Router results must not expose a trusted container ID")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


class LocalDockerRouterContainerManager:
    """Create a Router once and trust it only after exact Docker inspect read-back."""

    def __init__(self, provider: LocalDockerProvider) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        self.provider = provider

    @staticmethod
    def _is_missing(detail: str) -> bool:
        lowered = detail.lower()
        return any(marker in lowered for marker in _MISSING_MARKERS)

    @staticmethod
    def _is_timeout(detail: str) -> bool:
        lowered = detail.lower()
        return "timed out" in lowered or "timeout" in lowered

    def _classify_error(self, detail: str) -> RouterEnsureStatus:
        if self.provider._is_unavailable(detail) or self._is_timeout(detail):
            return "unavailable"
        return "failed"

    def _inspect(
        self, spec: DockerRouterContainerSpec,
    ) -> tuple[RouterEnsureStatus | Literal["missing", "verified"], str | None, str]:
        """Inspect only by deterministic name, then verify full immutable identity."""
        result, error = self.provider._execute(
            ["container", "inspect", "--format", ROUTER_CONTAINER_INSPECT_FORMAT, spec.container_name]
        )
        if error:
            return self._classify_error(error), None, error
        assert result is not None
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            if self._is_missing(output):
                return "missing", None, output or "Router container does not exist"
            return self._classify_error(output), None, output or "Docker Router container inspect failed"
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return "invalid_response", None, "Docker Router container inspect returned malformed JSON"
        verification = verify_router_container_inspection(payload, spec)
        if verification.status == "verified":
            return "verified", verification.container_id, ""
        return verification.status, None, verification.detail

    def ensure_router(
        self, spec: DockerRouterContainerSpec,
    ) -> DockerRouterContainerEnsureResult:
        """Inspect first; create only if absent; always inspect again after create.

        Existing mismatches are never removed or replaced. An ambiguous create
        result is resolved only by exact post-create inspection, never by assuming
        that Docker accepted the command. No route switch or app-container action
        is performed by this manager.
        """
        if not isinstance(spec, DockerRouterContainerSpec):
            raise TypeError("spec must be a DockerRouterContainerSpec")
        before_status, before_id, before_detail = self._inspect(spec)
        if before_status == "verified":
            return DockerRouterContainerEnsureResult("existing", before_id)
        if before_status != "missing":
            return DockerRouterContainerEnsureResult(
                before_status, detail=before_detail,  # type: ignore[arg-type]
            )

        create_result, create_error = self.provider._execute(spec.run_argv)
        create_succeeded = (
            create_error is None
            and create_result is not None
            and create_result.returncode == 0
        )
        create_detail = create_error or (
            ((create_result.stderr or create_result.stdout).strip())
            if create_result is not None else "Docker Router create did not return a result"
        )

        # This second inspect resolves races, timeouts, and lost create responses.
        after_status, after_id, after_detail = self._inspect(spec)
        if after_status == "verified":
            if create_succeeded:
                return DockerRouterContainerEnsureResult("created", after_id)
            return DockerRouterContainerEnsureResult(
                "existing", after_id,
                "Router container was verified after an ambiguous create response",
            )
        if after_status == "missing":
            if create_succeeded:
                return DockerRouterContainerEnsureResult(
                    "invalid_response",
                    detail="Docker run reported success but the Router container is absent on re-inspection",
                )
            status = self._classify_error(create_detail)
            return DockerRouterContainerEnsureResult(
                status, detail=(create_detail or after_detail)[:1000],
            )
        return DockerRouterContainerEnsureResult(
            after_status, detail=after_detail or create_detail,  # type: ignore[arg-type]
        )
