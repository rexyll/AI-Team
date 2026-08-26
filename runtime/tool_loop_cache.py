from __future__ import annotations

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


class ToolResultCache:
    """Conservative cache for exact repeated read-only tool calls.

    Only read_file/list_files are cacheable. Any tool that may mutate or execute
    workspace state invalidates the cache, so a cached read can never survive a
    known state-changing operation.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], CachedToolResult] = {}
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

    def lookup(self, tool_name: str, arguments: dict[str, Any]) -> CachedToolResult | None:
        if tool_name not in CACHEABLE_TOOLS:
            return None
        key = (tool_name, stable_hash(arguments))
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
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
        self._entries[(tool_name, arguments_hash)] = CachedToolResult(
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            result=deepcopy(result),
            source_execution_id=execution_id,
        )

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
