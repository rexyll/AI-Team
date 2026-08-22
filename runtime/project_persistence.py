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
from runtime.tool_execution_audit import ToolExecutionAudit
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
        payloads: list[dict[str, Any]] = []
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
                payloads.append(item)

        if not payloads:
            return None
        return ToolExecutionHistory.from_dict(payloads)

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
        
    def list_ids(self) -> list[str]:
        """Return persisted project ids in stable lexical order."""
        return sorted(
            path.stem
            for path in self.root.glob("*.json")
            if path.is_file()
        )

    def delete(self, project_id: str) -> None:
        """Delete exactly one persisted project snapshot."""
        path = self._path(project_id)

        if not path.is_file():
            raise KeyError(project_id)

        path.unlink()

    def checkpoint(
        self,
        project_id: str,
        *,
        plan: dict[str, Any] | None,
        task_manager: TaskManager,
        result: ProjectResult,
        tool_execution_history: ToolExecutionHistory | None = None,
    ) -> None:
        """Commit one complete runtime checkpoint as a single atomic snapshot.

        A checkpoint is deliberately stricter than ``update``: it represents a
        recoverable runtime boundary, so a complete ProjectResult is required
        and must describe exactly the supplied TaskManager state. All
        validation happens before the atomic replacement, preserving the
        previous snapshot when the candidate state is invalid.
        """
        if not isinstance(result, ProjectResult):
            raise TypeError("result must be a ProjectResult")

        path = self._path(project_id)
        if not path.exists():
            raise KeyError(project_id)
        if not path.is_file():
            raise ValueError(f"project payload is not a file: {project_id}")

        self._validate_snapshot_consistency(
            project_id,
            plan=plan,
            task_manager=task_manager,
            result=result,
        )
        payload = self._build_payload(
            project_id,
            plan,
            task_manager,
            result,
            tool_execution_history,
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

        return ProjectSnapshot(
            project_id=project_id,
            plan=plan,
            task_manager=task_manager,
            result=result,
            tool_execution_history=tool_execution_history,
        )

    def audit(self, project_id: str) -> ToolExecutionAudit:
        """Return a read-only audit view over the persisted project history."""
        snapshot = self.load(project_id)
        return ToolExecutionAudit(snapshot.tool_execution_history)

    def audit_consistency(self, project_id: str) -> dict[str, Any]:
        """Report whether persisted canonical history matches task-local history.

        The report is observational only. It deliberately does not reject or
        rewrite a snapshot because explicit project-level history remains the
        canonical persisted representation. A mismatch is therefore useful
        evidence of a boundary that has not yet been rehydrated into task
        runtime contexts; continuation can then restore the canonical history.
        """
        snapshot = self.load(project_id)
        canonical = snapshot.tool_execution_history.to_dict() if snapshot.tool_execution_history is not None else []
        contextual = self._history_from_task_manager(snapshot.task_manager)
        context_payload = contextual.to_dict() if contextual is not None else []

        canonical_by_id = {item["execution_id"]: item for item in canonical}
        context_by_id = {item["execution_id"]: item for item in context_payload}
        canonical_ids = set(canonical_by_id)
        context_ids = set(context_by_id)

        return {
            "project_id": project_id,
            "consistent": canonical_by_id == context_by_id,
            "canonical_count": len(canonical_by_id),
            "task_context_count": len(context_by_id),
            "missing_from_task_context": sorted(canonical_ids - context_ids),
            "missing_from_canonical": sorted(context_ids - canonical_ids),
            "conflicting_execution_ids": sorted(
                execution_id
                for execution_id in canonical_ids & context_ids
                if canonical_by_id[execution_id] != context_by_id[execution_id]
            ),
        }

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

        if result is None:
            return
        if result.project is not None and plan is not None:
            expected_project = plan.get("project")
            if expected_project is not None and result.project != expected_project:
                raise ValueError(
                    f"project snapshot result mismatch: {project_id}"
                )
        actual_statuses = {task.id: task.status for task in tasks}
        expected_completed = tuple(sorted(task_id for task_id, status in actual_statuses.items() if status == "completed"))
        expected_failed = tuple(sorted(task_id for task_id, status in actual_statuses.items() if status == "failed"))
        expected_blocked = tuple(sorted(task_id for task_id, status in actual_statuses.items() if status == "blocked"))
        if result.total_tasks != len(tasks):
            raise ValueError(f"project snapshot result mismatch: {project_id}")
        if result.completed_tasks != len(expected_completed):
            raise ValueError(f"project snapshot result mismatch: {project_id}")
        if tuple(sorted(result.failed_tasks)) != expected_failed:
            raise ValueError(f"project snapshot result mismatch: {project_id}")
        if tuple(sorted(result.blocked_tasks)) != expected_blocked:
            raise ValueError(f"project snapshot result mismatch: {project_id}")
        if tuple(sorted(result.completed_task_ids)) != expected_completed:
            raise ValueError(f"project snapshot result mismatch: {project_id}")

    @staticmethod
    def _restore_result(payload: Any) -> ProjectResult | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("project payload result must be a dictionary or None")
        try:
            return ProjectResult.from_dict(payload)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("project payload contains an invalid result") from exc

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent, text=True
        )
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise
