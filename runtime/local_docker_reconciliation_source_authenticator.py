"""Host source authenticator for a pinned Local Docker Engine.

This adapter authenticates runtime/route observations against an operator-pinned
Docker daemon ID. Docker CLI transport authentication (local socket ACL or the
configured Docker TLS context) remains part of the Host operating environment.
The adapter does not claim provider-operation inspection; LocalDockerProvider
continues to return unsupported for that separate capability.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Callable, Mapping

from runtime.deployment_reconciliation_evidence_collector import (
    EvidenceSourceRole,
    ReconciliationEvidenceCollectionError,
    ReconciliationEvidenceSourceAuthentication,
)
from runtime.local_docker_provider import LocalDockerProvider

_DAEMON_ID = re.compile(r"^[0-9a-f]{64}$")
_INFO_FORMAT = "{{.ID}}|{{.Name}}|{{.ServerVersion}}|{{.DockerRootDir}}"


class LocalDockerReconciliationEvidenceSourceAuthenticator:
    """Authenticate Docker runtime and Router observations against one pinned daemon.

    The expected daemon ID must come from trusted Host configuration, not from
    the response being authenticated. Every authentication call re-reads Docker
    Engine identity through the provider's fixed-argv command boundary and
    rejects daemon drift, malformed output, source-role confusion or scope
    mismatch. No deployment/runtime/router mutation is performed.
    """

    def __init__(
        self,
        provider: LocalDockerProvider,
        *,
        expected_daemon_id: str,
        source_ids: Mapping[str, str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        if not isinstance(expected_daemon_id, str) or not _DAEMON_ID.fullmatch(
            expected_daemon_id
        ):
            raise ValueError("expected_daemon_id must be a full lowercase Docker daemon ID")
        if not isinstance(source_ids, Mapping) or set(source_ids) != {"runtime", "route"}:
            raise ValueError("source_ids must define runtime and route")
        if any(not isinstance(v, str) or not v.strip() for v in source_ids.values()):
            raise ValueError("runtime and route source IDs must be non-empty")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self.provider = provider
        self.expected_daemon_id = expected_daemon_id
        self.source_ids = dict(source_ids)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ReconciliationEvidenceCollectionError(
                "Local Docker source authenticator clock must be timezone-aware"
            )
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _read_daemon_identity(self) -> tuple[str, str, str, str]:
        try:
            result, error = self.provider._execute(["info", "--format", _INFO_FORMAT])
        except Exception as exc:
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon identity inspection raised an exception"
            ) from exc
        if error is not None or result is None:
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon identity is unavailable"
            )
        if result.returncode != 0:
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon identity command failed"
            )
        fields = result.stdout.strip().split("|")
        if len(fields) != 4:
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon identity response is malformed"
            )
        daemon_id, name, server_version, docker_root_dir = fields
        if not _DAEMON_ID.fullmatch(daemon_id) or any(
            not isinstance(value, str) or not value.strip()
            for value in (name, server_version, docker_root_dir)
        ):
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon identity response has invalid fields"
            )
        if daemon_id != self.expected_daemon_id:
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon ID does not match the Host-pinned identity"
            )
        return daemon_id, name, server_version, docker_root_dir

    def authenticate_source(
        self,
        *,
        role: EvidenceSourceRole,
        source_id: str,
        provider: str,
        project: str,
        environment: str,
        response_digest_sha256: str,
        observed_at: str,
    ) -> ReconciliationEvidenceSourceAuthentication:
        """Return a response-bound source receipt for runtime or route reads."""
        if role not in {"runtime", "route"}:
            raise ReconciliationEvidenceCollectionError(
                "Local Docker cannot authenticate provider-operation inspection"
            )
        if provider != self.provider.name:
            raise ReconciliationEvidenceCollectionError(
                "Local Docker source provider does not match the requested scope"
            )
        if source_id != self.source_ids[role]:
            raise ReconciliationEvidenceCollectionError(
                "Local Docker source ID does not match Host configuration"
            )
        if (
            not isinstance(response_digest_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", response_digest_sha256)
        ):
            raise ReconciliationEvidenceCollectionError(
                "source response digest must be a lowercase SHA-256 digest"
            )
        if not isinstance(project, str) or not project.strip() or not isinstance(
            environment, str
        ) or not environment.strip():
            raise ReconciliationEvidenceCollectionError(
                "Docker source scope must include project and environment"
            )
        # Validate the observation timestamp before authorizing its source.
        try:
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ReconciliationEvidenceCollectionError(
                "Docker source observation timestamp is invalid"
            ) from exc
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ReconciliationEvidenceCollectionError(
                "Docker source observation timestamp must be timezone-aware"
            )

        daemon_id, name, server_version, docker_root_dir = self._read_daemon_identity()
        endpoint_identity = hashlib.sha256(
            json.dumps(
                {
                    "provider": provider,
                    "daemon_id": daemon_id,
                    "daemon_name": name,
                    "server_version": server_version,
                    "docker_root_dir": docker_root_dir,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ReconciliationEvidenceSourceAuthentication(
            role=role,
            source_id=source_id,
            provider=provider,
            project=project,
            environment=environment,
            response_digest_sha256=response_digest_sha256,
            endpoint_identity_digest_sha256=endpoint_identity,
            authenticated_at=self._now(),
        )
