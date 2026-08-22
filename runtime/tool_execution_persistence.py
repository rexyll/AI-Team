from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .tool_execution_history import ToolExecutionConflictError
from .tool_execution_record import ToolExecutionRecord


class ToolExecutionPersistenceAdapter:
    """Filesystem-backed persistence for immutable tool execution records."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(execution_id: str) -> str:
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError("execution_id must be a non-empty string")
        if Path(execution_id).name != execution_id or execution_id in {".", ".."}:
            raise ValueError("execution_id must be a simple filename-safe identifier")
        if any(sep in execution_id for sep in ("/", "\\")):
            raise ValueError("execution_id must not contain path separators")
        return execution_id

    def _path(self, execution_id: str) -> Path:
        return self.root / f"{self._validate_id(execution_id)}.json"

    def save(self, record: ToolExecutionRecord) -> None:
        if not isinstance(record, ToolExecutionRecord):
            raise TypeError("record must be a ToolExecutionRecord")
        path = self._path(record.execution_id)
        if path.exists():
            raise FileExistsError(path)

        payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
        temp = path.with_name(f".{path.name}.tmp")
        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        except Exception:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise

    def save_if_absent(self, record: ToolExecutionRecord) -> bool:
        """Persist a record once, treating an identical existing record as success.

        Returns ``True`` when a new file is created and ``False`` when the
        exact same immutable record already exists. A conflicting record with
        the same execution id is rejected with the same conflict type used by
        in-memory history and recovery.
        """
        if not isinstance(record, ToolExecutionRecord):
            raise TypeError("record must be a ToolExecutionRecord")

        path = self._path(record.execution_id)
        if path.exists():
            existing = self.load(record.execution_id)
            if existing == record:
                return False
            raise ToolExecutionConflictError(
                f"conflicting tool execution record for execution_id: {record.execution_id}"
            )

        self.save(record)
        return True

    def save_if_absent_many(self, records: Iterable[ToolExecutionRecord]) -> int:
        """Persist a batch with preflight conflict detection and rollback.

        Identical records already on disk are treated as idempotent. New
        records are staged before any target is replaced. If staging or the
        commit phase fails, files created by this batch are removed so callers
        do not observe a deliberately partial batch. Conflicting records use
        the same ``ToolExecutionConflictError`` as in-memory history.
        """
        incoming = list(records)
        for record in incoming:
            if not isinstance(record, ToolExecutionRecord):
                raise TypeError("records must contain ToolExecutionRecord values")

        unique: dict[str, ToolExecutionRecord] = {}
        for record in incoming:
            existing = unique.get(record.execution_id)
            if existing is not None and existing != record:
                raise ToolExecutionConflictError(
                    f"conflicting tool execution record for execution_id: {record.execution_id}"
                )
            unique[record.execution_id] = record

        pending: list[tuple[Path, str]] = []
        for execution_id, record in unique.items():
            path = self._path(execution_id)
            if path.exists():
                existing = self.load(execution_id)
                if existing != record:
                    raise ToolExecutionConflictError(
                        f"conflicting tool execution record for execution_id: {execution_id}"
                    )
                continue
            payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
            pending.append((path, payload))

        staged: list[tuple[Path, Path]] = []
        created: list[Path] = []
        try:
            for path, payload in pending:
                fd, temporary = tempfile.mkstemp(
                    prefix=f".{path.stem}-", suffix=".tmp", dir=self.root, text=True
                )
                temp_path = Path(temporary)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
                staged.append((temp_path, path))

            for temp_path, path in staged:
                os.replace(temp_path, path)
                created.append(path)

            return len(pending)
        except Exception:
            for temp_path, _ in staged:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
            for path in created:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise

    def load(self, execution_id: str) -> ToolExecutionRecord:
        path = self._path(execution_id)
        if not path.is_file():
            raise KeyError(execution_id)
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid tool execution record: {execution_id}") from exc
        try:
            record = ToolExecutionRecord.from_dict(payload)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid tool execution record: {execution_id}") from exc
        if record.execution_id != execution_id:
            raise ValueError("tool execution record identity does not match filename")
        return record

    def list_ids(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json") if path.is_file())

    def delete(self, execution_id: str) -> None:
        path = self._path(execution_id)
        if not path.is_file():
            raise KeyError(execution_id)
        path.unlink()
