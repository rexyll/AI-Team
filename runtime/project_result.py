from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProjectResult:
    success: bool
    project: str
    summary: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    pending_tasks: int
    tasks: list[Any] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.failed_tasks > 0