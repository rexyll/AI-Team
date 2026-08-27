from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskCheckpointSummary:
    """Compact state snapshot used when a developer task needs to resume.

    The summary intentionally contains evidence and state, not raw tool output.
    It is safe to pass across context-compaction boundaries because construction
    performs defensive copies of mutable inputs.
    """

    task_id: str
    status: str
    changed_files: tuple[str, ...]
    last_command: str | None
    command_count: int
    tool_call_count: int
    duplicate_tool_call_count: int
    retry_tool_call_count: int
    tool_categories: dict[str, int]
    recent_tools: tuple[str, ...]
    dependency_context: dict[str, Any]
    task_result: dict[str, Any]
    verification_evidence: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy({
            "task_id": self.task_id,
            "status": self.status,
            "changed_files": list(self.changed_files),
            "last_command": self.last_command,
            "command_count": self.command_count,
            "tool_call_count": self.tool_call_count,
            "duplicate_tool_call_count": self.duplicate_tool_call_count,
            "retry_tool_call_count": self.retry_tool_call_count,
            "tool_categories": self.tool_categories,
            "recent_tools": list(self.recent_tools),
            "dependency_context": self.dependency_context,
            "task_result": self.task_result,
            "verification_evidence": list(self.verification_evidence),
        })


def build_task_checkpoint_summary(
    *,
    task_id: str,
    status: str,
    telemetry: list[dict[str, Any]] | None = None,
    changed_files: list[str] | None = None,
    command_results: list[dict[str, Any]] | None = None,
    dependency_context: dict[str, Any] | None = None,
    task_result: dict[str, Any] | None = None,
) -> TaskCheckpointSummary:
    """Build a compact resume checkpoint from canonical task evidence."""
    telemetry = list(telemetry or [])
    categories = Counter(item.get("category") or "unknown" for item in telemetry)
    commands = [item for item in (command_results or []) if isinstance(item, dict)]
    verification = tuple(
        deepcopy(item) for item in commands
        if str(item.get("category") or "").lower() == "verification"
        or "pytest" in str(item.get("command") or "").lower()
        or "test" in str(item.get("command") or "").lower()
    )[-4:]
    unique_files = tuple(dict.fromkeys(str(path) for path in (changed_files or [])))
    recent_tools = tuple(str(item.get("tool_name") or "unknown") for item in telemetry[-4:])
    last_command = str(commands[-1]["command"]) if commands and commands[-1].get("command") else None

    return TaskCheckpointSummary(
        task_id=task_id,
        status=status,
        changed_files=unique_files,
        last_command=last_command,
        command_count=len(commands),
        tool_call_count=len(telemetry),
        duplicate_tool_call_count=sum(1 for item in telemetry if item.get("duplicate_of") is not None),
        retry_tool_call_count=sum(1 for item in telemetry if item.get("retry_of") is not None),
        tool_categories=dict(sorted(categories.items())),
        recent_tools=recent_tools,
        dependency_context=deepcopy(dependency_context or {}),
        task_result=deepcopy(task_result or {}),
        verification_evidence=verification,
    )
