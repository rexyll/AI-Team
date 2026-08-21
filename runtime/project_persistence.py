from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.project_result import ProjectResult
from runtime.task import Task
from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class ProjectSnapshot:
    """Runtime-neutral representation of one persisted project snapshot."""

    project_id: str
    plan: dict[str, Any] | None
    task_manager: TaskManager
    result: ProjectResult | None


class ProjectPersistenceAdapter:
    """File-backed persistence boundary for project execution snapshots."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if project_id in {".", ".."} or Path(project_id).name != project_id:
            raise ValueError("project_id must be a simple path-safe identifier")
        return self.root / f"{project_id}.json"

    @staticmethod
    def _build_payload(
        project_id: str,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None,
    ) -> dict[str, Any]:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if plan is not None and not isinstance(plan, dict):
            raise TypeError("plan must be a dictionary or None")
        if result is not None and not isinstance(result, ProjectResult):
            raise TypeError("result must be a ProjectResult or None")

        return {
            "project_id": project_id,
            "plan": plan,
            "tasks": [task.to_dict() for task in task_manager.get_all_tasks()],
            "result": result.to_dict() if result is not None else None,
        }

    def save(
        self,
        project_id: str,
        *,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None = None,
    ) -> None:
        path = self._path(project_id)
        if path.exists():
            raise FileExistsError(f"project already exists: {project_id}")

        payload = self._build_payload(
            project_id,
            plan,
            task_manager,
            result,
        )
        self._atomic_write(path, payload)

    def update(
        self,
        project_id: str,
        *,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None = None,
    ) -> None:
        """Replace an existing project snapshot atomically."""
        path = self._path(project_id)
        if not path.exists():
            raise KeyError(project_id)
        if not path.is_file():
            raise ValueError(f"project payload is not a file: {project_id}")

        payload = self._build_payload(
            project_id,
            plan,
            task_manager,
            result,
        )
        self._atomic_write(path, payload)

    def load(self, project_id: str) -> ProjectSnapshot:
        path = self._path(project_id)
        if not path.exists():
            raise KeyError(project_id)
        if not path.is_file():
            raise ValueError(f"project payload is not a file: {project_id}")

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid project payload: {project_id}") from exc

        if not isinstance(payload, dict):
            raise ValueError("project payload must be a dictionary")
        if payload.get("project_id") != project_id:
            raise ValueError("project payload identity mismatch")

        plan = payload.get("plan")
        if plan is not None and not isinstance(plan, dict):
            raise ValueError("project payload plan must be a dictionary or None")

        task_payloads = payload.get("tasks")
        if not isinstance(task_payloads, list):
            raise ValueError("project payload tasks must be a list")
        try:
            tasks = [Task.from_dict(item) for item in task_payloads]
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("project payload contains an invalid task") from exc

        result_payload = payload.get("result")
        result = self._restore_result(result_payload)

        return ProjectSnapshot(
            project_id=project_id,
            plan=plan,
            task_manager=TaskManager(tasks),
            result=result,
        )

    @staticmethod
    def _restore_result(payload: Any) -> ProjectResult | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("project payload result must be a dictionary or None")

        required = {
            "project",
            "success",
            "status",
            "total_tasks",
            "completed_tasks",
            "failed_tasks",
            "blocked_tasks",
        }
        if set(payload) != required:
            raise ValueError("project payload result has an invalid schema")

        failed_tasks = payload["failed_tasks"]
        blocked_tasks = payload["blocked_tasks"]
        if not isinstance(failed_tasks, list) or not isinstance(blocked_tasks, list):
            raise ValueError("project result task collections must be lists")
        if not isinstance(payload["success"], bool):
            raise ValueError("project result success must be a boolean")
        if not isinstance(payload["status"], str):
            raise ValueError("project result status must be a string")
        if not isinstance(payload["total_tasks"], int) or isinstance(payload["total_tasks"], bool):
            raise ValueError("project result total_tasks must be an integer")
        if not isinstance(payload["completed_tasks"], int) or isinstance(payload["completed_tasks"], bool):
            raise ValueError("project result completed_tasks must be an integer")

        return ProjectResult(
            project=payload["project"],
            success=payload["success"],
            status=payload["status"],
            total_tasks=payload["total_tasks"],
            completed_tasks=payload["completed_tasks"],
            failed_tasks=tuple(failed_tasks),
            blocked_tasks=tuple(blocked_tasks),
        )

    def load_task_manager(self, project_id: str) -> TaskManager:
        return self.load(project_id).task_manager

    def delete(self, project_id: str) -> None:
        path = self._path(project_id)
        if not path.exists():
            raise KeyError(project_id)
        path.unlink()

    def list_ids(self) -> list[str]:
        return sorted(
            path.stem
            for path in self.root.glob("*.json")
            if path.is_file()
        )

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.stem}-",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
