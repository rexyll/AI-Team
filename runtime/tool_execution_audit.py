from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord


class ToolExecutionAudit:
    """Read-only query boundary over a canonical tool execution snapshot.

    The audit layer deliberately owns a detached history snapshot. Persisted
    runtime state may continue to evolve after an audit object is created, but
    an audit query must remain deterministic and must never provide a mutation
    path back into the runtime or persistence layer.
    """

    def __init__(self, history: ToolExecutionHistory | None = None) -> None:
        if history is not None and not isinstance(history, ToolExecutionHistory):
            raise TypeError("history must be a ToolExecutionHistory or None")
        source = history if history is not None else ToolExecutionHistory()
        self._history = ToolExecutionHistory.from_dict(source.to_dict())

    @property
    def history(self) -> ToolExecutionHistory:
        """Return a detached history snapshot, never the audit's internal state."""
        return ToolExecutionHistory.from_dict(self._history.to_dict())

    def records(
        self,
        *,
        task_id: str | None = None,
        agent_role: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
    ) -> list[ToolExecutionRecord]:
        """Return detached records matching all supplied filters."""
        records: Iterable[ToolExecutionRecord] = (
            ToolExecutionRecord.from_dict(payload)
            for payload in self._history.to_dict()
        )
        if task_id is not None:
            records = (record for record in records if record.task_id == task_id)
        if agent_role is not None:
            records = (record for record in records if record.agent_role == agent_role)
        if tool_name is not None:
            records = (record for record in records if record.tool_name == tool_name)
        if status is not None:
            records = (record for record in records if record.status == status)
        return [record for record in records]

    def count(
        self,
        *,
        task_id: str | None = None,
        agent_role: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
    ) -> int:
        return len(
            self.records(
                task_id=task_id,
                agent_role=agent_role,
                tool_name=tool_name,
                status=status,
            )
        )

    def summary(self) -> dict[str, Any]:
        """Return deterministic aggregate counts without exposing mutable state."""
        records = self.records()
        by_status: dict[str, int] = {}
        by_tool: dict[str, int] = {}
        by_agent_role: dict[str, int] = {}
        for record in records:
            by_status[record.status] = by_status.get(record.status, 0) + 1
            by_tool[record.tool_name] = by_tool.get(record.tool_name, 0) + 1
            by_agent_role[record.agent_role] = by_agent_role.get(record.agent_role, 0) + 1
        return {
            "total": len(records),
            "by_status": dict(sorted(by_status.items())),
            "by_tool": dict(sorted(by_tool.items())),
            "by_agent_role": dict(sorted(by_agent_role.items())),
        }
