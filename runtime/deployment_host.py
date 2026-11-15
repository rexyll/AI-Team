"""Host startup integration for deployment replacement recovery inventory.

This lifecycle hook is intentionally read-only. It inspects the host-owned
SQLite journal before CLI operation dispatch, but never contacts Docker,
changes traffic, resumes a replacement, or releases a reservation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_replacement import DeploymentReplacementProvider
from runtime.deployment_replacement_manager import (
    DeploymentRecoveryInventoryItem,
    HostDeploymentReplacementManager,
)
from runtime.local_docker_provider import LocalDockerProvider


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
