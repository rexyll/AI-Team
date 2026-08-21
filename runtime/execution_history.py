from __future__ import annotations

from typing import Dict, List

from .execution_record import AgentExecutionRecord


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
