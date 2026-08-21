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
from runtime.tool_execution_history import ToolExecutionHistory


@dataclass(frozen=True)
class ProjectSnapshot:
    """Runtime-neutral representation of one persisted project snapshot."""

    project_id: str
    plan: dict[str, Any] | None
    task_manager: TaskManager
    result: ProjectResult | None
    tool_execution_history: ToolExecutionHistory | None = None


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
    def _history_from_task_manager(task_manager: TaskManager) -> ToolExecutionHistory | None:
        """Extract Developer tool history embedded in task runtime snapshots."""
        payload_by_id: dict[str, dict[str, Any]] = {}
        for task in task_manager.get_all_tasks():
            payload = task.context.get("tool_execution_history", [])
            if payload is None:
                continue
            if not isinstance(payload, list):
                raise ValueError(f"task {task.id} has invalid tool execution history payload")
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError(f"task {task.id} has an invalid tool execution record")
                execution_id = item.get("execution_id")
                if not isinstance(execution_id, str) or not execution_id:
                    raise ValueError(f"task {task.id} has a tool execution record without execution_id")
                if item.get("task_id") != task.id:
                    raise ValueError(
                        f"task {task.id} contains a tool execution record owned by another task"
                    )
                existing = payload_by_id.get(execution_id)
                if existing is not None and existing != item:
                    raise ValueError(f"conflicting tool execution record: {execution_id}")
                payload_by_id[execution_id] = item

        if not payload_by_id:
            return None
        return ToolExecutionHistory.from_dict(list(payload_by_id.values()))

    @staticmethod
    def _validate_history_matches_task_contexts(
        task_manager: TaskManager,
        history: ToolExecutionHistory | None,
    ) -> None:
        """Reject divergent project-level and task-level tool histories.

        During continuation the task context is the runtime source from which
        checkpoints rebuild the project history. If a caller supplies an
        explicit project history while task contexts already contain logs, the
        two representations must describe the same immutable records. This
        prevents a checkpoint from silently dropping old tool logs or creating
        two competing histories for the same task.
        """
        if history is None:
            return

        context_history = ProjectPersistenceAdapter._history_from_task_manager(task_manager)
        if context_history is None:
            return

        if context_history.to_dict() != history.to_dict():
            raise ValueError("project tool execution history does not match task context history")

    @staticmethod
    def _build_payload(
        project_id: str,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None,
        tool_execution_history: ToolExecutionHistory | None,
    ) -> dict[str, Any]:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if plan is not None and not isinstance(plan, dict):
            raise TypeError("plan must be a dictionary or None")
        if result is not None and not isinstance(result, ProjectResult):
            raise TypeError("result must be a ProjectResult or None")
        if tool_execution_history is not None and not isinstance(tool_execution_history, ToolExecutionHistory):
            raise TypeError("tool_execution_history must be a ToolExecutionHistory or None")

        if tool_execution_history is None:
            tool_execution_history = ProjectPersistenceAdapter._history_from_task_manager(task_manager)
        else:
            ProjectPersistenceAdapter._validate_tool_execution_history(
                task_manager,
                tool_execution_history,
            )
            ProjectPersistenceAdapter._validate_history_matches_task_contexts(
                task_manager,
                tool_execution_history,
            )

        return {
            "project_id": project_id,
            "plan": plan,
            "tasks": [task.to_dict() for task in task_manager.get_all_tasks()],
            "result": result.to_dict() if result is not None else None,
            "tool_execution_history": (
                tool_execution_history.to_dict()
                if tool_execution_history is not None
                else None
            ),
        }

    @staticmethod
    def _validate_tool_execution_history(
        task_manager: TaskManager,
        history: ToolExecutionHistory | None,
    ) -> None:
        """Ensure every persisted tool log belongs to a known task."""
        if history is None:
            return
        task_ids = {task.id for task in task_manager.get_all_tasks()}
        for record in history.to_dict():
            task_id = record.get("task_id")
            if task_id not in task_ids:
                raise ValueError(
                    f"tool execution history references unknown task: {task_id}"
                )

    def save(
        self,
        project_id: str,
        *,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None = None,
        tool_execution_history: ToolExecutionHistory | None = None,
    ) -> None:
        path = self._path(project_id)
        if path.exists():
            raise FileExistsError(f"project already exists: {project_id}")

        payload = self._build_payload(project_id, plan, task_manager, result, tool_execution_history)
        self._atomic_write(path, payload)

    def update(
        self,
        project_id: str,
        *,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None = None,
        tool_execution_history: ToolExecutionHistory | None = None,
    ) -> None:
        """Replace an existing project snapshot atomically."""
        path = self._path(project_id)
        if not path.exists():
            raise KeyError(project_id)
        if not path.is_file():
            raise ValueError(f"project payload is not a file: {project_id}")

        payload = self._build_payload(project_id, plan, task_manager, result, tool_execution_history)
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

        task_manager = TaskManager(tasks)
        history_payload = payload.get("tool_execution_history")
        try:
            tool_execution_history = (
                ToolExecutionHistory.from_dict(history_payload)
                if history_payload is not None
                else self._history_from_task_manager(task_manager)
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("project payload contains an invalid tool execution history") from exc

        self._validate_snapshot_consistency(project_id, plan=plan, task_manager=task_manager, result=result)
        self._validate_tool_execution_history(task_manager, tool_execution_history)
        self._validate_history_matches_task_contexts(task_manager, tool_execution_history)

        return ProjectSnapshot(
            project_id=project_id,
            plan=plan,
            task_manager=task_manager,
            result=result,
            tool_execution_history=tool_execution_history,
        )

    @staticmethod
    def _validate_snapshot_consistency(
        project_id: str,
        *,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult | None,
    ) -> None:
        """Validate only invariants that must survive persisted recovery."""
        tasks = task_manager.get_all_tasks()
        task_ids = [task.id for task in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError(f"project snapshot contains duplicate task ids: {project_id}")

        if plan is not None:
            plan_tasks = plan.get("tasks")
            if not isinstance(plan_tasks, list):
                raise ValueError(f"project snapshot plan has invalid tasks: {project_id}")
            plan_ids: list[str] = []
            for item in plan_tasks:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    raise ValueError(f"project snapshot plan contains an invalid task: {project_id}")
                plan_ids.append(item["id"])
            if len(plan_ids) != len(set(plan_ids)):
                raise ValueError(f"project snapshot plan contains duplicate task ids: {project_id}")
            if plan_ids and set(plan_ids) != set(task_ids):
                raise ValueError(f"project snapshot plan/task identity mismatch: {project_id}")

        if result is not None:
            project_name = None
            if plan is not None and isinstance(plan.get("project"), str):
                project_name = plan["project"]
            expected = ProjectResult.from_task_manager(task_manager, project=project_name)
            if result != expected:
                raise ValueError(f"project snapshot result mismatch: {project_id}")

    @staticmethod
    def _restore_result(payload: Any) -> ProjectResult | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("project payload result must be a dictionary or None")
        required = {"project", "success", "status", "total_tasks", "completed_tasks", "failed_tasks", "blocked_tasks"}
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
        return sorted(path.stem for path in self.root.glob("*.json") if path.is_file())

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent, text=True)
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
