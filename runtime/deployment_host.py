"""Host startup integration for deployment replacement recovery inventory.

This lifecycle hook is intentionally read-only. It inspects the host-owned
SQLite journal before CLI operation dispatch, but never contacts Docker,
changes traffic, resumes a replacement, or releases a reservation.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import DeploymentRecord, DeploymentRuntimeInspection
from runtime.deployment_replacement import DeploymentReplacementProvider, DeploymentTrafficReadback
from runtime.deployment_traffic_router import TrafficRouterScope
from runtime.deployment_replacement_manager import (
    DeploymentRecoveryInventoryItem,
    HostDeploymentReplacementManager,
)
from runtime.deployment_reconciliation_completion import (
    LocalDockerSynchronousOperationCompletionInspector,
)
from runtime.deployment_reconciliation_evidence_collector import (
    DecisionSpecificReconciliationEvidenceCollector,
)
from runtime.deployment_reconciliation_snapshot_reader import (
    DeploymentHistoryReconciliationSnapshotReader,
)
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_reconciliation_source_authenticator import (
    LocalDockerReconciliationEvidenceSourceAuthenticator,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _ManualReconciliationReadOnlyProvider:
    """Narrow provider facade for the operator report; it exposes no mutations."""

    def __init__(self, provider, history, route_adapters, route_failures) -> None:
        self.provider = provider
        self.history = history
        self.name = provider.name
        self.route_adapters = route_adapters
        self.route_failures = route_failures

    def inspect_reconciliation_runtime(
        self, deployment_id: str, runtime_id: str
    ) -> DeploymentRuntimeInspection:
        identity_inspector = getattr(self.provider, "inspect_runtime_identity", None)
        inspector = getattr(self.provider, "inspect_runtime", None)
        record = None
        try:
            if callable(identity_inspector):
                # The journal may contain the immutable runtime ID before its
                # DeploymentRecord is committed. Inspect that exact ID directly.
                observation = identity_inspector(deployment_id, runtime_id)
            else:
                record = self.history.get(deployment_id)
                if (
                    not isinstance(record, DeploymentRecord)
                    or record.provider != self.name
                    or record.deployment_id != deployment_id
                    or record.container_id != runtime_id
                ):
                    return DeploymentRuntimeInspection(
                        provider=self.name, deployment_id=deployment_id,
                        expected_runtime_id=runtime_id, observed_runtime_id=None,
                        identity_match=False, status="invalid_response",
                        runtime_state="unknown", health_status="unknown",
                        checked_at=_utc_now(),
                        probe="manual reconciliation durable deployment lookup",
                        detail="No durable deployment record matches the exact journal runtime identity",
                    )
                if not callable(inspector):
                    return DeploymentRuntimeInspection(
                        provider=self.name, deployment_id=deployment_id,
                        expected_runtime_id=runtime_id, observed_runtime_id=None,
                        identity_match=False, status="unavailable",
                        runtime_state="unknown", health_status="unavailable",
                        checked_at=_utc_now(),
                        probe="manual reconciliation immutable runtime read-back",
                        detail="Underlying provider does not expose immutable runtime inspection",
                    )
                observation = inspector(record)
        except Exception as exc:
            return DeploymentRuntimeInspection(
                provider=self.name, deployment_id=deployment_id,
                expected_runtime_id=runtime_id, observed_runtime_id=None,
                identity_match=False, status="unavailable",
                runtime_state="unknown", health_status="unavailable",
                checked_at=_utc_now(),
                probe="manual reconciliation immutable runtime read-back",
                detail=f"Immutable runtime inspection raised {type(exc).__name__}",
            )
        if (
            not isinstance(observation, DeploymentRuntimeInspection)
            or observation.provider != self.name
            or observation.deployment_id != deployment_id
            or observation.expected_runtime_id != runtime_id
        ):
            return DeploymentRuntimeInspection(
                provider=self.name, deployment_id=deployment_id,
                expected_runtime_id=runtime_id, observed_runtime_id=None,
                identity_match=False, status="invalid_response",
                runtime_state="unknown", health_status="unknown",
                checked_at=_utc_now(),
                probe="manual reconciliation immutable runtime read-back",
                detail="Provider inspection did not match the exact journal runtime identity",
            )
        return observation

    def inspect_reconciliation_route(self, journal) -> DeploymentTrafficReadback:
        key = (journal.provider, journal.project, journal.environment)
        adapter = self.route_adapters.get(key)
        if adapter is not None:
            return adapter.inspect_reconciliation_route(journal)
        status, detail = self.route_failures.get(
            key,
            ("not_found", "No existing durable Router scope is available for read-only inspection"),
        )
        return DeploymentTrafficReadback(
            provider=self.name, status=status, checked_at=_utc_now(),
            router_runtime_id=None, registry_active_slot=None,
            registry_active_runtime_id=None, live_active_slot=None,
            effective_runtime_id=None, route_generation=None, detail=detail,
        )


class _MissingReconciliationRouteInspector:
    """Read-only route source that records an absent durable Router scope."""

    def __init__(self, scope: TrafficRouterScope, detail: str) -> None:
        self.name = scope.provider
        self.scope = scope
        self.detail = detail

    def inspect_reconciliation_route(
        self, journal
    ) -> DeploymentTrafficReadback:
        return DeploymentTrafficReadback(
            provider=self.name,
            status="not_found",
            checked_at=_utc_now(),
            router_runtime_id=None,
            registry_active_slot=None,
            registry_active_runtime_id=None,
            live_active_slot=None,
            effective_runtime_id=None,
            route_generation=None,
            detail=self.detail,
        )


@dataclass(frozen=True)
class DeploymentHostStartupResult:
    history_path: str
    provider: str
    inventory: tuple[DeploymentRecoveryInventoryItem, ...]

    def to_dict(self) -> dict:
        """Return a JSON-compatible, metadata-only inventory snapshot."""
        return {
            "status": "ok",
            "history_path": self.history_path,
            "provider": self.provider,
            "unfinished_replacements": len(self.inventory),
            "inventory": [asdict(item) for item in self.inventory],
        }


class DeploymentHostRuntime:
    """Initialize host deployment state and inventory unfinished replacements.

    The history path is opt-in: normal CLI users do not get a database created
    unless they set AI_TEAM_DEPLOYMENT_HISTORY or pass --deployment-history.
    Once configured, the main CLI invokes this runtime on every process
    startup. LocalDockerProvider construction itself performs no Docker I/O,
    and the recovery inventory path only reads SQLite.
    """

    def __init__(
        self,
        history_path: str | Path,
        *,
        provider: LocalDockerProvider | None = None,
        create_if_missing: bool = True,
    ) -> None:
        if not isinstance(history_path, (str, Path)) or not str(history_path).strip():
            raise ValueError("history_path must be a non-empty path")
        if not isinstance(create_if_missing, bool):
            raise TypeError("create_if_missing must be a bool")
        self.history_path = Path(history_path).expanduser().resolve()
        self.create_if_missing = create_if_missing
        self.provider = provider or LocalDockerProvider()
        name = getattr(self.provider, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("deployment provider must expose a non-empty name")

    def build_reconciliation_source_authenticator(
        self,
        *,
        operation_receipt_store_path: str | Path | None = None,
    ) -> LocalDockerReconciliationEvidenceSourceAuthenticator:
        """Build the pinned Local Docker source authenticator from Host config.

        The expected daemon identity is a mandatory operator-provisioned value.
        This method performs no Docker I/O and does not enable a collector or
        approval authority. Provider operation inspection remains unsupported
        by LocalDockerProvider, so the Local Docker reconciliation gate stays
        closed until that separate capability is provided.
        """
        if not isinstance(self.provider, LocalDockerProvider):
            raise RuntimeError(
                "pinned Local Docker source authentication requires LocalDockerProvider"
            )
        expected_daemon_id = os.environ.get(
            "AI_TEAM_DOCKER_EXPECTED_DAEMON_ID", ""
        ).strip()
        if not expected_daemon_id:
            raise RuntimeError(
                "AI_TEAM_DOCKER_EXPECTED_DAEMON_ID must be provisioned by the Host operator"
            )
        source_ids = {
            "runtime": "docker-local-daemon-runtime",
            "route": "docker-local-daemon-router",
        }
        if operation_receipt_store_path is not None:
            source_ids["provider_operation"] = "docker-local-host-call-receipts"
        return LocalDockerReconciliationEvidenceSourceAuthenticator(
            self.provider,
            expected_daemon_id=expected_daemon_id,
            source_ids=source_ids,
            operation_receipt_store_path=operation_receipt_store_path,
        )

    def build_reconciliation_snapshot_reader(
        self,
        operation_id: str,
        *,
        max_evidence_age_seconds: float = 120.0,
    ) -> DeploymentHistoryReconciliationSnapshotReader:
        """Compose the read-only Local Docker snapshot path for one journal scope.

        The builder reads only existing Host journal/Router registry state. It
        never creates/adopts a Router scope and performs no Docker commands.
        This composes a distinct Host-synchronous completion witness from the
        existing read-only receipt sidecar. It does not change the provider's
        native inspect_operation capability. Runtime and route evidence still
        require a pinned Docker daemon identity and independent live read-back.
        This path is read-only, not an approval/decision handler.
        """
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("operation_id must be a non-empty string")
        if not self.history_path.is_file():
            raise FileNotFoundError(
                f"deployment history database does not exist: {self.history_path}"
            )
        if not isinstance(self.provider, LocalDockerProvider):
            raise RuntimeError(
                "Local Docker reconciliation snapshot composition requires LocalDockerProvider"
            )
        history = DeploymentHistoryStore(self.history_path, read_only=True)
        journal = history.get_replacement(operation_id)
        if journal is None:
            raise KeyError("replacement operation does not exist in Host history")
        if journal.provider != self.provider.name:
            raise ValueError("replacement journal provider does not match the Host provider")
        scope = TrafficRouterScope(
            journal.provider, journal.project, journal.environment
        )

        router = history.get_traffic_router(scope)
        state_record = history.get_traffic_router_state_record(scope)
        if router is None or state_record is None:
            missing = (
                "Durable Router registry or Host Router state record is missing; "
                "read-only reconciliation route evidence is unavailable"
            )
            route_inspector = _MissingReconciliationRouteInspector(scope, missing)
        else:
            from runtime.local_docker_router_host import LocalDockerRouterHostManager
            from runtime.local_docker_routed_app import LocalDockerRoutedAppManager
            from runtime.local_docker_router_slot_manager import LocalDockerRouterSlotManager
            from runtime.local_docker_router_replacement_provider import (
                LocalDockerRouterReplacementProvider,
            )

            router_host = LocalDockerRouterHostManager(
                self.provider,
                history,
                Path(__file__).resolve().parents[1],
                Path(state_record.directory).parent,
            )
            route_inspector = LocalDockerRouterReplacementProvider(
                self.provider,
                history,
                router_host,
                LocalDockerRoutedAppManager(self.provider),
                LocalDockerRouterSlotManager(self.provider),
                scope,
                router.port_bindings,
            )

        receipt_store_path = self.history_path.with_name(
            f"{self.history_path.stem}.provider-operations.sqlite3"
        )
        completion_inspector = LocalDockerSynchronousOperationCompletionInspector(
            receipt_store_path,
            max_evidence_age_seconds=max_evidence_age_seconds,
        )
        collector = DecisionSpecificReconciliationEvidenceCollector(
            provider_operation_inspector=None,
            host_synchronous_completion_inspector=completion_inspector,
            runtime_inspector=self.provider,
            route_inspector=route_inspector,
            source_authenticator=self.build_reconciliation_source_authenticator(
                operation_receipt_store_path=receipt_store_path
            ),
            source_ids={
                "provider_operation": "docker-local-host-call-receipts",
                "runtime": "docker-local-daemon-runtime",
                "route": "docker-local-daemon-router",
            },
            max_evidence_age_seconds=max_evidence_age_seconds,
        )
        return DeploymentHistoryReconciliationSnapshotReader(
            history,
            collector,
            reader_id="docker-local-deployment-host-snapshot-reader",
        )

    def inspect_recovery(self) -> dict:
        """Explicitly inspect recorded containers; never mutate host state."""
        if not self.history_path.is_file():
            raise FileNotFoundError(
                f"deployment history database does not exist: {self.history_path}"
            )
        history = DeploymentHistoryStore(self.history_path, read_only=True)
        manager = HostDeploymentReplacementManager(
            cast(DeploymentReplacementProvider, self.provider),
            history,
        )
        observations = manager.inspect_recovery_runtimes()
        return {
            "status": "ok",
            "history_path": str(history.path),
            "provider": self.provider.name,
            "unfinished_replacements": len(observations),
            "observations": [asdict(item) for item in observations],
            "route_readback_available": False,
            "automatic_recovery_allowed": False,
        }


    def inspect_manual_reconciliation_readback(self) -> dict:
        """Return operator evidence for runtimes and live traffic, without mutation."""
        if not self.history_path.is_file():
            raise FileNotFoundError(
                f"deployment history database does not exist: {self.history_path}"
            )
        history = DeploymentHistoryStore(self.history_path, read_only=True)
        journals = history.list_active_replacements(provider=self.provider.name)
        route_adapters = {}
        route_failures = {}

        if journals:
            from runtime.local_docker_router_host import LocalDockerRouterHostManager
            from runtime.local_docker_routed_app import LocalDockerRoutedAppManager
            from runtime.local_docker_router_slot_manager import LocalDockerRouterSlotManager
            from runtime.local_docker_router_replacement_provider import LocalDockerRouterReplacementProvider

            scopes = sorted({
                (item.provider, item.project, item.environment) for item in journals
            })
            for key in scopes:
                scope = TrafficRouterScope(*key)
                try:
                    router = history.get_traffic_router(scope)
                    if router is None:
                        route_failures[key] = (
                            "not_found",
                            "No durable Router registry exists; read-back will not create or adopt a scope",
                        )
                        continue
                    state_record = history.get_traffic_router_state_record(scope)
                    if state_record is None:
                        route_failures[key] = (
                            "not_found",
                            "Durable Router Host state record is missing; read-back is unavailable",
                        )
                        continue
                    if not isinstance(self.provider, LocalDockerProvider):
                        route_failures[key] = (
                            "unsupported",
                            "The configured provider does not support the Local Docker Router read-only adapter",
                        )
                        continue
                    router_host = LocalDockerRouterHostManager(
                        self.provider, history, Path(__file__).resolve().parents[1],
                        Path(state_record.directory).parent,
                    )
                    route_adapters[key] = LocalDockerRouterReplacementProvider(
                        self.provider, history, router_host,
                        LocalDockerRoutedAppManager(self.provider),
                        LocalDockerRouterSlotManager(self.provider),
                        scope, router.port_bindings,
                    )
                except Exception as exc:
                    route_failures[key] = (
                        "invalid_response",
                        f"Durable Router read-back setup failed: {type(exc).__name__}",
                    )

        facade = _ManualReconciliationReadOnlyProvider(
            self.provider, history, route_adapters, route_failures
        )
        manager = HostDeploymentReplacementManager(
            cast(DeploymentReplacementProvider, facade), history
        )
        readbacks = []
        for project, environment in sorted({
            (item.project, item.environment) for item in journals
        }):
            readbacks.extend(manager.manual_reconciliation_readback(
                project=project, environment=environment
            ))
        readbacks.sort(key=lambda item: item.operation_id)
        return {
            "status": "ok",
            "history_path": str(history.path),
            "provider": self.provider.name,
            "unfinished_replacements": len(readbacks),
            "readbacks": [asdict(item) for item in readbacks],
            "read_only": True,
            "automatic_action": "none",
            "automatic_recovery_allowed": False,
        }

    def start(self) -> DeploymentHostStartupResult:
        """Open the durable host store and return its read-only recovery view."""
        if not self.history_path.is_file():
            if not self.create_if_missing:
                raise FileNotFoundError(
                    f"deployment history database does not exist: {self.history_path}"
                )
            # First opt-in Host startup creates the private schema once. All
            # subsequent inventory reads use SQLite URI mode=ro.
            DeploymentHistoryStore(self.history_path)
        history = DeploymentHistoryStore(self.history_path, read_only=True)
        # The inventory manager only consumes provider.name on this code path.
        # Its replacement operation remains disabled for LocalDockerProvider
        # because _supports_replacement() checks the full capability at runtime.
        manager = HostDeploymentReplacementManager(
            cast(DeploymentReplacementProvider, self.provider),
            history,
        )
        inventory = manager.recovery_inventory()
        return DeploymentHostStartupResult(
            history_path=str(history.path),
            provider=self.provider.name,
            inventory=inventory,
        )
