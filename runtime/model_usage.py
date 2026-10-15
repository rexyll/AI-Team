from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from runtime.model_governance import ModelRoute, ModelUsage


@dataclass(frozen=True)
class ModelUsageRecord:
    """Immutable attribution event for one successful provider invocation."""

    project_id: str
    usage: ModelUsage
    route: ModelRoute | None = None


class ModelUsageLedger:
    """Thread-safe project-scoped usage ledger.

    The ledger records observed provider usage but does not perform admission,
    enforce budgets, or select routes. Those decisions remain the responsibility
    of ModelGovernance.
    """

    def __init__(self) -> None:
        self._usage: dict[str, ModelUsage] = {}
        self._records: list[ModelUsageRecord] = []
        self._lock = RLock()

    def record(
        self,
        project_id: str,
        usage: ModelUsage,
        *,
        route: ModelRoute | None = None,
    ) -> ModelUsageRecord:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if not isinstance(usage, ModelUsage):
            raise TypeError("usage must be a ModelUsage")
        if route is not None and not isinstance(route, ModelRoute):
            raise TypeError("route must be a ModelRoute or None")
        project_id = project_id.strip()
        record = ModelUsageRecord(project_id=project_id, usage=usage, route=route)
        with self._lock:
            self._usage[project_id] = self._usage.get(project_id, ModelUsage()).add(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                llm_calls=usage.llm_calls,
            )
            self._records.append(record)
        return record

    def usage_for(self, project_id: str) -> ModelUsage:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        with self._lock:
            return self._usage.get(project_id.strip(), ModelUsage())

    def records(self, project_id: str | None = None) -> tuple[ModelUsageRecord, ...]:
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string")
        with self._lock:
            records = tuple(self._records)
        if project_id is None:
            return records
        project_id = project_id.strip()
        return tuple(record for record in records if record.project_id == project_id)
