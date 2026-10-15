from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .tool_loop_telemetry import stable_hash


CACHEABLE_TOOLS = frozenset({"read_file", "list_files"})
MUTATING_TOOLS = frozenset({"write_file", "move_file", "delete_file", "run_command", "git_command"})


@dataclass(frozen=True)
class CachedToolResult:
    tool_name: str
    arguments_hash: str
    result: Any
    source_execution_id: str

    def context_evidence(self) -> str:
        """Return a compact marker suitable for a repeated read-only tool request."""
        return (
            "TOOL RESULT REUSED: exact read-only request was already executed; "
            f"no tool execution was repeated. Source execution={self.source_execution_id}. "
            "Use the earlier tool evidence for the full result."
        )


class ToolResultCache:
    """Conservative, bounded cache for exact repeated read-only tool calls."""

    DEFAULT_MAX_ENTRIES = 64

    def __init__(self, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be > 0")
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str], CachedToolResult] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def invalidations(self) -> int:
        return self._invalidations

    def contains(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Return whether an exact cache entry exists without changing cache state."""
        if tool_name not in CACHEABLE_TOOLS:
            return False
        key = (tool_name, stable_hash(arguments))
        return key in self._entries

    def lookup(self, tool_name: str, arguments: dict[str, Any]) -> CachedToolResult | None:
        if tool_name not in CACHEABLE_TOOLS:
            return None
        key = (tool_name, stable_hash(arguments))
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        self._entries.move_to_end(key)
        self._hits += 1
        return CachedToolResult(
            tool_name=entry.tool_name,
            arguments_hash=entry.arguments_hash,
            result=deepcopy(entry.result),
            source_execution_id=entry.source_execution_id,
        )

    def store(self, *, tool_name: str, arguments: dict[str, Any], result: Any, execution_id: str) -> None:
        if tool_name not in CACHEABLE_TOOLS:
            return
        arguments_hash = stable_hash(arguments)
        key = (tool_name, arguments_hash)
        self._entries[key] = CachedToolResult(
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            result=deepcopy(result),
            source_execution_id=execution_id,
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def invalidate_for(self, tool_name: str) -> None:
        if tool_name not in MUTATING_TOOLS:
            return
        if self._entries:
            self._entries.clear()
            self._invalidations += 1

    def clear(self) -> None:
        if self._entries:
            self._entries.clear()
            self._invalidations += 1
