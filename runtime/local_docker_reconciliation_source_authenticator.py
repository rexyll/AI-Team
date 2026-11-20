"""Host source authenticator for a pinned Local Docker Engine.

This adapter authenticates runtime/route observations against an operator-pinned
Docker daemon ID. Docker CLI transport authentication (local socket ACL or the
configured Docker TLS context) remains part of the Host operating environment.
A separately configured Host receipt source is authenticated only as a local
Host trust-boundary observation, never as provider-native operation inspection.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat as stat_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from runtime.deployment_reconciliation_evidence_collector import (
    EvidenceSourceRole,
    ReconciliationEvidenceCollectionError,
    ReconciliationEvidenceSourceAuthentication,
)
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider

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
        operation_receipt_store_path: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        if not isinstance(expected_daemon_id, str) or not _DAEMON_ID.fullmatch(
            expected_daemon_id
        ):
            raise ValueError("expected_daemon_id must be a full lowercase Docker daemon ID")
        if not isinstance(source_ids, Mapping) or set(source_ids) not in (
            {"runtime", "route"},
            {"provider_operation", "runtime", "route"},
        ):
            raise ValueError("source_ids must define runtime/route and optional provider_operation")
        if any(not isinstance(v, str) or not v.strip() for v in source_ids.values()):
            raise ValueError("configured source IDs must be non-empty")
        if ("provider_operation" in source_ids) != (operation_receipt_store_path is not None):
            raise ValueError(
                "provider_operation source ID and receipt store path must be configured together"
            )
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self.provider = provider
        self.expected_daemon_id = expected_daemon_id
        self.source_ids = dict(source_ids)
        self.operation_receipt_store_path = (
            Path(operation_receipt_store_path).expanduser().resolve()
            if operation_receipt_store_path is not None
            else None
        )
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
        if not isinstance(result, DockerCommandResult):
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon identity command returned an invalid result type"
            )
        if not isinstance(result.stdout, str) or not isinstance(result.stderr, str):
            raise ReconciliationEvidenceCollectionError(
                "Docker daemon identity command returned invalid output fields"
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
        """Authenticate pinned Docker observations or the local Host receipt store."""
        if role == "provider_operation" and self.operation_receipt_store_path is None:
            raise ReconciliationEvidenceCollectionError(
                "Local Docker cannot authenticate provider-operation inspection without a Host receipt store"
            )
        if role not in self.source_ids:
            raise ReconciliationEvidenceCollectionError(
                "Local Docker source role is not configured by the Host"
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

        if role == "provider_operation":
            receipt_path = self.operation_receipt_store_path
            if receipt_path is None:
                raise ReconciliationEvidenceCollectionError(
                    "Local Docker Host receipt store is not configured"
                )
            try:
                metadata = receipt_path.stat()
            except OSError as exc:
                raise ReconciliationEvidenceCollectionError(
                    "Host provider-call receipt store is unavailable"
                ) from exc
            if not receipt_path.is_file():
                raise ReconciliationEvidenceCollectionError(
                    "Host provider-call receipt source is not a regular file"
                )
            parent_metadata = receipt_path.parent.stat()
            if os.name == "posix":
                current_uid = os.getuid()
                if (
                    metadata.st_uid != current_uid
                    or stat_module.S_IMODE(metadata.st_mode) & 0o077
                    or parent_metadata.st_uid != current_uid
                    or stat_module.S_IMODE(parent_metadata.st_mode) & 0o022
                ):
                    raise ReconciliationEvidenceCollectionError(
                        "Host provider-call receipt store ownership or permissions are unsafe"
                    )
            endpoint_identity = hashlib.sha256(
                json.dumps(
                    {
                        "source_kind": "host-local-provider-call-receipt-store",
                        "provider": provider,
                        "path": str(receipt_path),
                        "device": metadata.st_dev,
                        "inode": metadata.st_ino,
                        "mode": stat_module.S_IMODE(metadata.st_mode),
                        "uid": getattr(metadata, "st_uid", None),
                        "gid": getattr(metadata, "st_gid", None),
                        "parent_device": parent_metadata.st_dev,
                        "parent_inode": parent_metadata.st_ino,
                        "parent_mode": stat_module.S_IMODE(parent_metadata.st_mode),
                        "parent_uid": getattr(parent_metadata, "st_uid", None),
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

        if role not in {"runtime", "route"}:
            raise ReconciliationEvidenceCollectionError(
                "unsupported Local Docker source role"
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
