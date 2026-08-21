from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from .execution_record import AgentExecutionRecord

if TYPE_CHECKING:
    from .execution_record_persistence import ExecutionRecordPersistenceAdapter


class ExecutionHistory:
    """In-memory ordered index of immutable agent execution records."""

    def __init__(self) -> None:
        self._records: Dict[str, AgentExecutionRecord] = {}

    def append(self, record: AgentExecutionRecord) -> None:
        if not isinstance(record, AgentExecutionRecord):
            raise TypeError("record must be an AgentExecutionRecord")
        if record.execution_id in self._records:
            raise ValueError(f"execution_id already exists: {record.execution_id}")
        self._records[record.execution_id] = record

    def get(self, execution_id: str) -> AgentExecutionRecord:
        try:
            return self._records[execution_id]
        except KeyError as exc:
            raise KeyError(execution_id) from exc

    def list_for_task(self, task_id: str) -> List[AgentExecutionRecord]:
        records = [record for record in self._records.values() if record.task_id == task_id]
        return sorted(records, key=lambda record: (record.attempt, record.execution_id))

    def list_for_project(self, project_id: str) -> List[AgentExecutionRecord]:
        records = [record for record in self._records.values() if record.project_id == project_id]
        return sorted(records, key=lambda record: (record.started_at, record.execution_id))

    def latest_attempt(self, task_id: str) -> AgentExecutionRecord | None:
        records = self.list_for_task(task_id)
        return records[-1] if records else None

    def save(self, adapter: "ExecutionRecordPersistenceAdapter") -> None:
        """Persist every record through the execution-record adapter."""
        from .execution_record_persistence import ExecutionRecordPersistenceAdapter

        if not isinstance(adapter, ExecutionRecordPersistenceAdapter):
            raise TypeError("adapter must be an ExecutionRecordPersistenceAdapter")
        for record in self._records.values():
            try:
                adapter.save(record)
            except FileExistsError:
                existing = adapter.load(record.execution_id)
                if existing != record:
                    raise ValueError(
                        f"persisted execution record conflicts with history: {record.execution_id}"
                    )

    @classmethod
    def load(cls, adapter: "ExecutionRecordPersistenceAdapter") -> "ExecutionHistory":
        from .execution_record_persistence import ExecutionRecordPersistenceAdapter

        if not isinstance(adapter, ExecutionRecordPersistenceAdapter):
            raise TypeError("adapter must be an ExecutionRecordPersistenceAdapter")
        history = cls()
        for execution_id in adapter.list_ids():
            history.append(adapter.load(execution_id))
        return history
