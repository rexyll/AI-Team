"""Per-lease dependency environment provisioning for Developer tasks.

Mutable environments are created inside a DeveloperWorkspaceManager lease and
are discarded with it. No virtualenv or node_modules tree is copied from or
merged back into the canonical deliverable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.project_adapters import (
    DEFAULT_PROJECT_ADAPTER_REGISTRY,
    ProjectAdapterExecutor,
    ProjectAdapterRegistry,
)
from runtime.tool_invocation_service import ToolInvocationService


class ProjectEnvironmentProvisioner:
    """Install one detected project's dependencies into the active lease."""

    def __init__(
        self,
        *,
        registry: ProjectAdapterRegistry | None = None,
        invocation_service: ToolInvocationService | None = None,
    ) -> None:
        self._registry = registry or DEFAULT_PROJECT_ADAPTER_REGISTRY
        self._service = invocation_service or ToolInvocationService()
        self._executor = ProjectAdapterExecutor(self._service)

    def prepare(
        self,
        root: str | Path,
        *,
        task_id: str,
        execution_id: str,
    ) -> dict[str, Any]:
        project_root = Path(root).resolve()
        try:
            detection = self._registry.resolve(project_root)
        except LookupError:
            return {
                "status": "skipped",
                "reason": "no supported project adapter detected",
            }
        except (KeyError, ValueError) as exc:
            return {
                "status": "unsupported",
                "reason": str(exc),
            }

        plan = self._registry.plan(
            project_root,
            "install",
            adapter_name=detection.adapter,
        )
        result = self._executor.execute(
            plan,
            role="developer",
            task_id=task_id,
            execution_id=execution_id,
        )
        return {
            "status": result["status"],
            "adapter": detection.adapter,
            "language": detection.language,
            "signals": list(detection.signals),
            "reason": result.get("reason"),
            "action": result,
            "tool_execution_history": self._service.history.to_dict(),
        }
