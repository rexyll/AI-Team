from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .execution_record import AgentExecutionRecord


class ExecutionRecordPersistenceAdapter:
    """Filesystem-backed persistence for immutable agent execution records."""

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
        execution_id = self._validate_id(execution_id)
        return self.root / f"{execution_id}.json"

    def save(self, record: AgentExecutionRecord) -> None:
        if not isinstance(record, AgentExecutionRecord):
            raise TypeError("record must be an AgentExecutionRecord")
        path = self._path(record.execution_id)
        if path.exists():
            raise FileExistsError(path)

        payload = record.to_dict()
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        temp = path.with_name(f".{path.name}.tmp")
        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        except Exception:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise

    def load(self, execution_id: str) -> AgentExecutionRecord:
        path = self._path(execution_id)
        if not path.is_file():
            raise KeyError(execution_id)
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid execution record: {execution_id}") from exc
        try:
            record = AgentExecutionRecord.from_dict(payload)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid execution record: {execution_id}") from exc
        if record.execution_id != execution_id:
            raise ValueError("execution record identity does not match filename")
        return record

    def list_ids(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json") if path.is_file())

    def delete(self, execution_id: str) -> None:
        path = self._path(execution_id)
        if not path.is_file():
            raise KeyError(execution_id)
        path.unlink()
