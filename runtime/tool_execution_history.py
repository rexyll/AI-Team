from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from .tool_execution_record import ToolExecutionRecord

if TYPE_CHECKING:
    from .tool_execution_persistence import ToolExecutionPersistenceAdapter


class ToolExecutionConflictError(FileExistsError, ValueError):
    """Raised when one execution id maps to different immutable records."""


class ToolExecutionHistory:
    """Ordered in-memory index of immutable tool execution records."""

    def __init__(self) -> None:
        self._records: dict[str, ToolExecutionRecord] = {}

    @staticmethod
    def _conflict(execution_id: str) -> ToolExecutionConflictError:
        return ToolExecutionConflictError(
            f"conflicting tool execution record for execution_id: {execution_id}"
        )

    def append(self, record: ToolExecutionRecord) -> None:
        if not isinstance(record, ToolExecutionRecord):
            raise TypeError("record must be a ToolExecutionRecord")
        if record.execution_id in self._records:
            raise ValueError(f"execution_id already exists: {record.execution_id}")
        self._records[record.execution_id] = record

    def append_if_absent(self, record: ToolExecutionRecord) -> bool:
        """Add a record unless an identical immutable record already exists."""
        if not isinstance(record, ToolExecutionRecord):
            raise TypeError("record must be a ToolExecutionRecord")
        existing = self._records.get(record.execution_id)
        if existing is None:
            self._records[record.execution_id] = record
            return True
        if existing == record:
            return False
        raise self._conflict(record.execution_id)

    def merge(self, records: Iterable[ToolExecutionRecord]) -> int:
        """Merge records atomically by execution-id identity."""
        incoming = list(records)
        for record in incoming:
            if not isinstance(record, ToolExecutionRecord):
                raise TypeError("records must contain ToolExecutionRecord values")

        pending: dict[str, ToolExecutionRecord] = {}
        for record in incoming:
            existing = self._records.get(record.execution_id)
            if existing is None:
                previous = pending.get(record.execution_id)
                if previous is not None and previous != record:
                    raise self._conflict(record.execution_id)
                pending[record.execution_id] = record
            elif existing != record:
                raise self._conflict(record.execution_id)

        self._records.update(pending)
        return len(pending)

    def get(self, execution_id: str) -> ToolExecutionRecord:
        try:
            return self._records[execution_id]
        except KeyError as exc:
            raise KeyError(execution_id) from exc

    def list_for_task(self, task_id: str) -> list[ToolExecutionRecord]:
        records = [record for record in self._records.values() if record.task_id == task_id]
        return sorted(records, key=lambda record: (record.started_at, record.execution_id))

    def list_for_tool(self, tool_name: str) -> list[ToolExecutionRecord]:
        records = [record for record in self._records.values() if record.tool_name == tool_name]
        return sorted(records, key=lambda record: (record.started_at, record.execution_id))

    def __len__(self) -> int:
        return len(self._records)

    def to_dict(self) -> list[dict]:
        return [record.to_dict() for record in self._records.values()]

    def to_context_dict(self) -> list[dict]:
        """Project records into the stable Task.context representation."""
        return [record.to_context_dict() for record in self._records.values()]

    @classmethod
    def from_dict(cls, payload: list[dict]) -> "ToolExecutionHistory":
        if not isinstance(payload, list):
            raise TypeError("tool execution history payload must be a list")
        history = cls()
        history.merge(ToolExecutionRecord.from_dict(item) for item in payload)
        return history

    def save(self, adapter: "ToolExecutionPersistenceAdapter") -> None:
        from .tool_execution_persistence import ToolExecutionPersistenceAdapter

        if not isinstance(adapter, ToolExecutionPersistenceAdapter):
            raise TypeError("adapter must be a ToolExecutionPersistenceAdapter")
        for record in self._records.values():
            adapter.save(record)

    def save_if_absent(self, adapter: "ToolExecutionPersistenceAdapter") -> int:
        """Persist the whole history as one idempotent batch."""
        from .tool_execution_persistence import ToolExecutionPersistenceAdapter

        if not isinstance(adapter, ToolExecutionPersistenceAdapter):
            raise TypeError("adapter must be a ToolExecutionPersistenceAdapter")
        return adapter.save_if_absent_many(self._records.values())
