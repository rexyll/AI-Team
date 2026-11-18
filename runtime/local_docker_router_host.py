"""Host-owned lifecycle orchestration for one durable Local Docker Router scope.

The first call may create the network, private state files and Router container,
then bind their immutable identities and file digests into DeploymentHistoryStore.
Calls for an existing registry entry never recreate persistent scope resources
or rewrite router files: they inspect the registered network/container and
image by immutable identity, run the pinned config validator in a temporary
network-none/read-only container, and reload persisted files without resetting
the active selector. Missing or mismatched resources require manual
reconciliation; they are never recreated or silently adopted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Literal
from uuid import uuid4

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_traffic_router import (
    TrafficPortBinding,
    TrafficRouterRecord,
    TrafficRouterScope,
)
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_config_validator import LocalDockerRouterConfigValidator
from runtime.local_docker_router_container import (
    DockerRouterContainerSpec,
    build_router_container_spec,
)
from runtime.local_docker_router_container_manager import LocalDockerRouterContainerManager
from runtime.local_docker_router_image import (
    DockerRouterImageIdentity,
    LocalDockerRouterImageManager,
)
from runtime.local_docker_router_network import (
    DockerRouterNetworkRecord,
    DockerRouterNetworkSpec,
    LocalDockerRouterNetworkManager,
    build_router_network_spec,
)
from runtime.local_docker_router_state import (
    LocalDockerRouterStateStore,
    RouterStateRecord,
)

HostRouterStatus = Literal[
    "created",
    "ready",
    "unavailable",
    "unsupported",
    "failed",
    "mismatch",
    "invalid_response",
    "manual_reconciliation_required",
]


@dataclass(frozen=True)
class LocalDockerRouterHostResult:
    """Trusted Router Host state returned only after full identity verification."""

    status: HostRouterStatus
    router_record: TrafficRouterRecord | None = None
    state_record: RouterStateRecord | None = None
    network: DockerRouterNetworkRecord | None = None
    image: DockerRouterImageIdentity | None = None
    container_spec: DockerRouterContainerSpec | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {
            "created",
            "ready",
            "unavailable",
            "unsupported",
            "failed",
            "mismatch",
            "invalid_response",
            "manual_reconciliation_required",
        }:
            raise ValueError("invalid Router Host status")
        trusted = (
            self.router_record,
            self.state_record,
            self.network,
            self.image,
            self.container_spec,
        )
        if self.status in {"created", "ready"}:
            if any(item is None for item in trusted):
                raise ValueError("trusted Router Host result requires registry, state, network, image and spec")
            assert self.router_record is not None
            assert self.state_record is not None
            assert self.network is not None
            assert self.image is not None
            assert self.container_spec is not None
            expected_network = build_router_network_spec(self.router_record.scope)
            if (
                self.router_record.network_name != self.network.network_name
                or self.router_record.network_id != self.network.network_id
                or self.network.network_name != expected_network.network_name
                or self.network.scope_fingerprint != expected_network.scope_fingerprint
                or self.router_record.port_bindings != self.container_spec.port_bindings
                or self.container_spec.network_name != self.network.network_name
                or self.container_spec.network_id != self.network.network_id
                or self.container_spec.scope_fingerprint != self.network.scope_fingerprint
                or self.container_spec.image_id != self.image.image_id
                or self.state_record.network_name != self.network.network_name
                or self.state_record.scope_fingerprint != self.network.scope_fingerprint
                or Path(self.container_spec.config_path) != Path(self.state_record.config_path)
                or Path(self.container_spec.active_slot_map_path) != Path(self.state_record.active_slot_map_path)
                or self.container_spec.server_state_sha256 != self.state_record.server_state_sha256
            ):
                raise ValueError("trusted Router Host result contains conflicting immutable resource identities")
        elif any(item is not None for item in trusted):
            raise ValueError("unverified Router Host result must not expose trusted resource records")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LocalDockerRouterHostManager:
    """Create a Router scope once; later calls only validate and reload it."""

    def __init__(
        self,
        provider: LocalDockerProvider,
        history: DeploymentHistoryStore,
        repository_root: str | Path,
        state_root: str | Path,
    ) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        if not isinstance(history, DeploymentHistoryStore):
            raise TypeError("history must be a DeploymentHistoryStore")
        if not isinstance(repository_root, (str, Path)) or not str(repository_root).strip():
            raise TypeError("repository_root must be a non-empty path")
        if not isinstance(state_root, (str, Path)) or not str(state_root).strip():
            raise TypeError("state_root must be a non-empty path")
        self.provider = provider
        self.history = history
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.state_root = Path(state_root).expanduser().absolute()
        self.state_store = LocalDockerRouterStateStore(self.state_root)
        self.network_manager = LocalDockerRouterNetworkManager(provider)
        self.image_manager = LocalDockerRouterImageManager(provider, self.repository_root)
        self.config_validator = LocalDockerRouterConfigValidator(provider)
        self.container_manager = LocalDockerRouterContainerManager(provider)

    @staticmethod
    def _validate_bindings(
        port_bindings: tuple[TrafficPortBinding, ...],
    ) -> tuple[TrafficPortBinding, ...]:
        if not isinstance(port_bindings, tuple) or not port_bindings or any(
            not isinstance(item, TrafficPortBinding) for item in port_bindings
        ):
            raise ValueError("port_bindings must be a non-empty tuple of TCP bindings")
        ordered = tuple(sorted(port_bindings, key=lambda item: item.host_port))
        if len({item.host_port for item in ordered}) != len(ordered):
            raise ValueError("Router host ports must be unique")
        return ordered

    @staticmethod
    def _is_missing_container(detail: str) -> bool:
        lowered = detail.lower()
        return "no such object" in lowered or "no such container" in lowered

    def _inspect_unregistered_container(self, container_name: str) -> tuple[str, str]:
        result, error = self.provider._execute(
            ["container", "inspect", "--format", "{{.Id}}", container_name]
        )
        if error:
            status = "unavailable" if self.provider._is_unavailable(error) or "timeout" in error.lower() else "failed"
            return status, error
        assert result is not None
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode == 0:
            return "exists", output or "Router container exists without a durable Host registry entry"
        if self._is_missing_container(output):
            return "missing", output
        status = "unavailable" if self.provider._is_unavailable(output) or "timeout" in output.lower() else "failed"
        return status, output or "Router container preflight inspection failed"

    def ensure_router(
        self,
        scope: TrafficRouterScope,
        port_bindings: tuple[TrafficPortBinding, ...],
    ) -> LocalDockerRouterHostResult:
        """Ensure a new scope or read-only verify an existing durable scope.

        Existing-registry path never calls network/container create or state
        persistence. A missing container/network is reported for manual
        reconciliation; the manager does not replace an immutable runtime ID.
        """
        if not isinstance(scope, TrafficRouterScope):
            raise TypeError("scope must be a TrafficRouterScope")
        bindings = self._validate_bindings(port_bindings)
        network_spec = build_router_network_spec(scope)
        try:
            self.state_store._check_no_symlink_components(self.state_root)
            existing = self.history.get_traffic_router(scope)
        except Exception as exc:
            return LocalDockerRouterHostResult(
                "failed", detail=f"Host Router registry preflight failed: {type(exc).__name__}: {str(exc)[:700]}"
            )

        if existing is None:
            return self._create_new_scope(scope, bindings, network_spec)
        return self._verify_existing_scope(scope, bindings, network_spec, existing)

    def inspect_existing_scope_readonly(
        self,
        scope: TrafficRouterScope,
        port_bindings: tuple[TrafficPortBinding, ...],
    ) -> LocalDockerRouterHostResult:
        """Verify an already-registered Router scope without Docker mutations.

        Unlike ensure_router(), this API never creates a missing scope and
        skips the temporary-container HAProxy syntax check. It verifies the
        digest-bound Host files, immutable network/image/container identities
        using inspect-only Docker commands, then returns the trusted records.
        """
        if not isinstance(scope, TrafficRouterScope):
            raise TypeError("scope must be a TrafficRouterScope")
        bindings = self._validate_bindings(port_bindings)
        network_spec = build_router_network_spec(scope)
        try:
            self.state_store._check_no_symlink_components(self.state_root)
            existing = self.history.get_traffic_router(scope)
        except Exception as exc:
            return LocalDockerRouterHostResult(
                "failed",
                detail=f"Read-only Router registry preflight failed: {type(exc).__name__}: {str(exc)[:700]}",
            )
        if existing is None:
            return LocalDockerRouterHostResult(
                "manual_reconciliation_required",
                detail="No durable Router registry exists; read-only inspection will not create or adopt one",
            )
        return self._verify_existing_scope(
            scope, bindings, network_spec, existing, validate_config=False
        )

    def _create_new_scope(
        self,
        scope: TrafficRouterScope,
        bindings: tuple[TrafficPortBinding, ...],
        network_spec: DockerRouterNetworkSpec,
    ) -> LocalDockerRouterHostResult:
        scope_directory = self.state_root / network_spec.network_name
        try:
            scope_directory.lstat()
        except FileNotFoundError:
            pass
        else:
            return LocalDockerRouterHostResult(
                "manual_reconciliation_required",
                detail="Router state directory exists without a durable scope registry; refusing to overwrite or adopt it",
            )

        container_name = f"ai-team-router-c-{network_spec.scope_fingerprint[:20]}"
        container_status, container_detail = self._inspect_unregistered_container(container_name)
        if container_status == "exists":
            return LocalDockerRouterHostResult(
                "manual_reconciliation_required",
                detail="Router container exists without a durable scope registry; refusing to adopt or recreate it",
            )
        if container_status != "missing":
            return LocalDockerRouterHostResult(
                container_status, detail=container_detail
            )

        image_result = self.image_manager.build_and_verify()
        if image_result.status != "verified" or image_result.identity is None:
            status = image_result.status if image_result.status in {"unavailable", "unsupported"} else "failed"
            return LocalDockerRouterHostResult(
                status, detail=image_result.detail or "Pinned Router image identity could not be verified"
            )

        network_result = self.network_manager.ensure_network(scope)
        if network_result.status != "created" or network_result.record is None:
            if network_result.status == "existing":
                return LocalDockerRouterHostResult(
                    "manual_reconciliation_required",
                    detail="Scope network exists without a durable Router registry; refusing to adopt it",
                )
            status = network_result.status if network_result.status in {
                "unavailable", "unsupported", "invalid_response"
            } else "failed"
            return LocalDockerRouterHostResult(
                status, detail=network_result.detail or "Scope bridge could not be created and verified"
            )

        persisted = self.state_store.persist(scope, bindings, active_slot=None)
        if persisted.status != "persisted" or persisted.record is None:
            status = "unsupported" if persisted.status == "unsupported" else "failed"
            return LocalDockerRouterHostResult(
                status, detail=persisted.detail or "Initial private Router state could not be persisted"
            )
        state_record = persisted.record

        validation = self.config_validator.validate(
            image_result.identity, state_record, expected_active_slot=None
        )
        if validation.status != "valid":
            status = validation.status if validation.status in {"unavailable", "unsupported"} else "failed"
            return LocalDockerRouterHostResult(
                status, detail=validation.detail or "Generated HAProxy config did not validate"
            )

        try:
            spec = build_router_container_spec(
                scope,
                bindings,
                network_result.record,
                image_result.identity,
                state_record,
                expected_active_slot=None,
            )
        except (TypeError, ValueError, OSError) as exc:
            return LocalDockerRouterHostResult(
                "failed", detail=f"Router container spec validation failed: {type(exc).__name__}: {str(exc)[:700]}"
            )

        ensured = self.container_manager.ensure_router(spec)
        if ensured.status not in {"created", "existing"} or ensured.container_id is None:
            status = ensured.status if ensured.status in {
                "unavailable", "invalid_response"
            } else "failed"
            return LocalDockerRouterHostResult(
                status, detail=ensured.detail or "Router container could not be created and inspected"
            )

        now = _utc_now()
        record = TrafficRouterRecord(
            scope=scope,
            router_deployment_id=f"router-{network_spec.scope_fingerprint[:20]}",
            router_runtime_id=ensured.container_id,
            network_name=network_result.record.network_name,
            network_id=network_result.record.network_id,
            port_bindings=bindings,
            active_slot=None,
            active_target=None,
            route_generation=uuid4().hex,
            created_at=now,
            slot_targets=(),
        )
        try:
            self.history.create_traffic_router(record, state_record)
        except Exception as exc:
            # Router is deliberately left running. Deleting it after an
            # ambiguous SQLite failure could interrupt a concurrently adopted
            # scope. Registry absence forces manual reconciliation on retry.
            return LocalDockerRouterHostResult(
                "manual_reconciliation_required",
                detail=f"Router was created but its durable registry commit failed: {type(exc).__name__}: {str(exc)[:700]}",
            )
        return LocalDockerRouterHostResult(
            "created", record, state_record, network_result.record,
            image_result.identity, spec,
        )

    def _inspect_router_image_id(
        self, router_runtime_id: str
    ) -> tuple[str, str | None, str]:
        """Read the image identity from the registered immutable Router container."""
        if not isinstance(router_runtime_id, str) or not re.fullmatch(
            r"[0-9a-f]{64}", router_runtime_id
        ):
            return "invalid_response", None, "Router registry runtime ID is not a full immutable Docker ID"
        result, error = self.provider._execute(
            ["container", "inspect", "--format", "{{.Image}}", router_runtime_id]
        )
        if error:
            status = (
                "unavailable"
                if self.provider._is_unavailable(error) or "timeout" in error.lower()
                else "failed"
            )
            return status, None, error
        assert result is not None
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            if self._is_missing_container(output):
                return "missing", None, output or "Registered immutable Router container is missing"
            status = (
                "unavailable"
                if self.provider._is_unavailable(output) or "timeout" in output.lower()
                else "failed"
            )
            return status, None, output or "Router image identity inspect failed"
        image_id = result.stdout.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            return "invalid_response", None, "Registered Router container did not report a full immutable image ID"
        return "verified", image_id, ""

    def _verify_existing_scope(
        self,
        scope: TrafficRouterScope,
        bindings: tuple[TrafficPortBinding, ...],
        network_spec: DockerRouterNetworkSpec,
        record: TrafficRouterRecord,
        *,
        validate_config: bool = True,
    ) -> LocalDockerRouterHostResult:
        if (
            record.port_bindings != bindings
            or record.network_name != network_spec.network_name
            or record.network_id is None
        ):
            return LocalDockerRouterHostResult(
                "mismatch", detail="Durable Router registry scope, port bindings, or immutable network identity differs"
            )
        try:
            state_record = self.history.get_traffic_router_state_record(scope)
        except Exception as exc:
            return LocalDockerRouterHostResult(
                "failed", detail=f"Durable Router state metadata is corrupt: {type(exc).__name__}: {str(exc)[:700]}"
            )
        if state_record is None:
            return LocalDockerRouterHostResult(
                "manual_reconciliation_required",
                detail="Durable Router registry has no digest-bound Host state record",
            )

        loaded = self.state_store.load(
            scope, bindings, expected_record=state_record
        )
        if loaded.status != "loaded":
            status = "unsupported" if loaded.status == "unsupported" else "mismatch"
            return LocalDockerRouterHostResult(
                status, detail=loaded.detail or "Persisted Router files failed read-only reload verification"
            )

        network_status, network_record, network_detail = self.network_manager._inspect(network_spec)
        if network_status != "verified" or network_record is None:
            status = "unavailable" if network_status == "unavailable" else "mismatch"
            return LocalDockerRouterHostResult(
                status, detail=network_detail or "Durable Router network identity cannot be inspected"
            )
        if network_record.network_id != record.network_id:
            return LocalDockerRouterHostResult(
                "mismatch", detail="Docker network immutable ID differs from the durable Router registry"
            )

        image_status, image_id, image_detail = self._inspect_router_image_id(
            record.router_runtime_id
        )
        if image_status == "missing":
            return LocalDockerRouterHostResult(
                "manual_reconciliation_required",
                detail="Registered immutable Router container is missing; image identity cannot be recovered safely",
            )
        if image_status != "verified" or image_id is None:
            status = image_status if image_status in {"unavailable", "invalid_response"} else "mismatch"
            return LocalDockerRouterHostResult(
                status, detail=image_detail or "Existing Router image identity could not be read"
            )
        image_result = self.image_manager.inspect_image(image_id)
        if image_result.status != "verified" or image_result.identity is None:
            status = image_result.status if image_result.status in {"unavailable", "unsupported"} else "mismatch"
            return LocalDockerRouterHostResult(
                status, detail=image_result.detail or "Registered immutable Router image failed pinned contract verification"
            )

        if validate_config:
            validation = self.config_validator.validate(
                image_result.identity,
                state_record,
                expected_active_slot=record.active_slot,
            )
            if validation.status != "valid":
                status = validation.status if validation.status in {"unavailable", "unsupported"} else "mismatch"
                return LocalDockerRouterHostResult(
                    status, detail=validation.detail or "Persisted active-slot map/config failed HAProxy validation"
                )
    

        try:
            spec = build_router_container_spec(
                scope,
                bindings,
                network_record,
                image_result.identity,
                state_record,
                expected_active_slot=record.active_slot,
            )
        except (TypeError, ValueError, OSError) as exc:
            return LocalDockerRouterHostResult(
                "mismatch", detail=f"Persisted Router container spec failed validation: {type(exc).__name__}: {str(exc)[:700]}"
            )

        inspect_status, runtime_id, detail = self.container_manager._inspect(spec)
        if inspect_status == "missing":
            return LocalDockerRouterHostResult(
                "manual_reconciliation_required",
                detail="Durable Router container is missing; automatic recreation would change immutable runtime identity",
            )
        if inspect_status != "verified" or runtime_id is None:
            status = inspect_status if inspect_status in {"unavailable", "invalid_response"} else "mismatch"
            return LocalDockerRouterHostResult(
                status, detail=detail or "Existing Router container failed immutable inspect verification"
            )
        if runtime_id != record.router_runtime_id:
            return LocalDockerRouterHostResult(
                "mismatch", detail="Router container immutable ID differs from the durable Host registry"
            )
        return LocalDockerRouterHostResult(
            "ready", record, state_record, network_record, image_result.identity, spec,
        )
