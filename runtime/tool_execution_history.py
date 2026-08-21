from __future__ import annotations

from typing import TYPE_CHECKING

from .tool_execution_record import ToolExecutionRecord

if TYPE_CHECKING:
    from .tool_execution_persistence import ToolExecutionPersistenceAdapter


class ToolExecutionHistory:
    """Ordered in-memory index of immutable tool execution records."""

    def __init__(self) -> None:
        self._records: dict[str, ToolExecutionRecord] = {}

    def append(self, record: ToolExecutionRecord) -> None:
        if not isinstance(record, ToolExecutionRecord):
            raise TypeError("record must be a ToolExecutionRecord")
        if record.execution_id in self._records:
            raise ValueError(f"execution_id already exists: {record.execution_id}")
        self._records[record.execution_id] = record

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

    @classmethod
    def from_dict(cls, payload: list[dict]) -> "ToolExecutionHistory":
        if not isinstance(payload, list):
            raise TypeError("tool execution history payload must be a list")
        history = cls()
        for item in payload:
            history.append(ToolExecutionRecord.from_dict(item))
        return history

    def save(self, adapter: "ToolExecutionPersistenceAdapter") -> None:
        from .tool_execution_persistence import ToolExecutionPersistenceAdapter

        if not isinstance(adapter, ToolExecutionPersistenceAdapter):
            raise TypeError("adapter must be a ToolExecutionPersistenceAdapter")
        for record in self._records.values():
            adapter.save(record)
