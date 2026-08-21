from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.project_result import ProjectResult
from runtime.task import Task
from runtime.task_manager import TaskManager


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

    def save(
        self,
        project_id: str,
        *,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None = None,
    ) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if plan is not None and not isinstance(plan, dict):
            raise TypeError("plan must be a dictionary or None")
        if result is not None and not isinstance(result, ProjectResult):
            raise TypeError("result must be a ProjectResult or None")

        path = self._path(project_id)
        if path.exists():
            raise FileExistsError(f"project already exists: {project_id}")

        payload: dict[str, Any] = {
            "project_id": project_id,
            "plan": plan,
            "tasks": [task.to_dict() for task in task_manager.get_all_tasks()],
            "result": result.to_dict() if result is not None else None,
        }

        self._atomic_write(path, payload)

    def load(self, project_id: str) -> dict[str, Any]:
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
        if not isinstance(payload.get("tasks"), list):
            raise ValueError("project payload tasks must be a list")

        # Validate persisted Task schemas without returning runtime objects.
        for task_payload in payload["tasks"]:
            Task.from_dict(task_payload)

        result_payload = payload.get("result")
        if result_payload is not None and not isinstance(result_payload, dict):
            raise ValueError("project payload result must be a dictionary or None")

        return payload

    def load_task_manager(self, project_id: str) -> TaskManager:
        payload = self.load(project_id)
        return TaskManager([Task.from_dict(item) for item in payload["tasks"]])

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
