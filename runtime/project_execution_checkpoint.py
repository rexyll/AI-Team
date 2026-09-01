from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from runtime.project_scheduler import ProjectExecutionScope
from runtime.workflow_checkpoint import WorkflowCheckpoint, WorkflowCheckpointError


class ProjectExecutionCheckpointError(ValueError):
    """Raised when a project execution checkpoint is missing or invalid."""


CHECKPOINT_VERSION = 1
RECOVERABLE_STATUSES = frozenset({"admitted", "started"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "released"})
VALID_STATUSES = RECOVERABLE_STATUSES | TERMINAL_STATUSES


@dataclass(frozen=True)
class ProjectExecutionCheckpoint:
    """Immutable durable snapshot for one admitted project execution.

    The checkpoint records only execution identity, project scope, lifecycle
    status, and the existing canonical task checkpoint. It does not own task
    lifecycle mutation or resource accounting.
    """

    reservation_id: str
    scope: ProjectExecutionScope
    task_id: str
    status: str
    task_checkpoint: WorkflowCheckpoint
    version: int = CHECKPOINT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.reservation_id, str) or not self.reservation_id.strip():
            raise ProjectExecutionCheckpointError("reservation_id must be a non-empty string")
        if not isinstance(self.scope, ProjectExecutionScope):
            raise ProjectExecutionCheckpointError("scope must be a ProjectExecutionScope")
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ProjectExecutionCheckpointError("task_id must be a non-empty string")
        if not isinstance(self.status, str) or self.status not in VALID_STATUSES:
            raise ProjectExecutionCheckpointError(f"unsupported checkpoint status: {self.status!r}")
        if not isinstance(self.task_checkpoint, WorkflowCheckpoint):
            raise ProjectExecutionCheckpointError("task_checkpoint must be a WorkflowCheckpoint")
        if self.task_checkpoint.task_id != self.task_id:
            raise ProjectExecutionCheckpointError("task checkpoint task_id does not match execution task_id")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version != CHECKPOINT_VERSION:
            raise ProjectExecutionCheckpointError("unsupported checkpoint version")

    @property
    def project_id(self) -> str:
        return self.scope.project_id

    @property
    def recoverable(self) -> bool:
        return self.status in RECOVERABLE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "reservation_id": self.reservation_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "status": self.status,
            "task_checkpoint": self.task_checkpoint.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectExecutionCheckpoint":
        if not isinstance(payload, dict):
            raise ProjectExecutionCheckpointError("checkpoint must be an object")
        try:
            task_checkpoint = WorkflowCheckpoint.from_dict(payload.get("task_checkpoint"))
            scope = ProjectExecutionScope(payload.get("project_id", ""))
            return cls(
                version=payload.get("version", 0),
                reservation_id=payload.get("reservation_id", ""),
                scope=scope,
                task_id=payload.get("task_id", ""),
                status=payload.get("status", ""),
                task_checkpoint=task_checkpoint,
            )
        except WorkflowCheckpointError as exc:
            raise ProjectExecutionCheckpointError("invalid task checkpoint") from exc
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ProjectExecutionCheckpointError):
                raise
            raise ProjectExecutionCheckpointError("invalid project execution checkpoint") from exc


class ProjectExecutionCheckpointStore:
    """Filesystem-backed durable store for project execution checkpoints."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _validate_id(reservation_id: str) -> str:
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise ValueError("reservation_id must be a non-empty string")
        if Path(reservation_id).name != reservation_id or reservation_id in {".", ".."}:
            raise ValueError("reservation_id must be a simple filename-safe identifier")
        if any(sep in reservation_id for sep in ("/", "\\")):
            raise ValueError("reservation_id must not contain path separators")
        return reservation_id

    def _path(self, reservation_id: str) -> Path:
        return self.root / f"{self._validate_id(reservation_id)}.json"

    def save(self, checkpoint: ProjectExecutionCheckpoint) -> None:
        if not isinstance(checkpoint, ProjectExecutionCheckpoint):
            raise TypeError("checkpoint must be a ProjectExecutionCheckpoint")
        with self._lock:
            path = self._path(checkpoint.reservation_id)
            self._atomic_replace(path, checkpoint.to_dict())

    def load(self, reservation_id: str) -> ProjectExecutionCheckpoint:
        path = self._path(reservation_id)
        if not path.is_file():
            raise KeyError(reservation_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = ProjectExecutionCheckpoint.from_dict(payload)
        except (OSError, json.JSONDecodeError, ProjectExecutionCheckpointError) as exc:
            raise ProjectExecutionCheckpointError(
                f"invalid project execution checkpoint: {reservation_id}"
            ) from exc
        if checkpoint.reservation_id != reservation_id:
            raise ProjectExecutionCheckpointError("checkpoint identity does not match filename")
        return checkpoint

    def list_all(self) -> tuple[ProjectExecutionCheckpoint, ...]:
        with self._lock:
            checkpoints = [self.load(path.stem) for path in sorted(self.root.glob("*.json")) if path.is_file()]
        return tuple(checkpoints)

    def list_recoverable(self, project_id: str | None = None) -> tuple[ProjectExecutionCheckpoint, ...]:
        if project_id is not None:
            scope = ProjectExecutionScope(project_id)
        else:
            scope = None
        checkpoints = [checkpoint for checkpoint in self.list_all() if checkpoint.recoverable]
        if scope is not None:
            checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint.scope == scope]
        return tuple(checkpoints)

    def delete(self, reservation_id: str) -> None:
        path = self._path(reservation_id)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError as exc:
                raise KeyError(reservation_id) from exc

    @staticmethod
    def _atomic_replace(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent, text=True
        )
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                fd = -1
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            if fd != -1:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise
