from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mcp_bridge.workspace import IGNORED_DIRECTORIES, MCPWorkspaceBoundary

DEFAULT_MAX_WRITE_BYTES = 512 * 1024
MAX_WRITE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class WorkspaceMutationEvent:
    """Auditable description of one completed workspace mutation."""

    operation: str
    path: str
    bytes_written: int = 0


MutationAuditSink = Callable[[WorkspaceMutationEvent], None]


class MCPWorkspaceMutationBoundary:
    """Host-owned, bounded mutation boundary for the authorized workspace.

    This adapter deliberately does not reuse the generic filesystem tool. All
    MCP mutations cross the canonical workspace boundary first, reject ignored
    metadata directories, enforce payload limits, and emit an audit event only
    after a successful mutation.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        audit_sink: MutationAuditSink | None = None,
    ) -> None:
        self._boundary = MCPWorkspaceBoundary(workspace_root)
        self._audit_sink = audit_sink

    @property
    def root(self) -> Path:
        return self._boundary.root

    def write_file(
        self,
        path: str,
        content: str,
        *,
        max_bytes: int = DEFAULT_MAX_WRITE_BYTES,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Create or update one UTF-8 text file inside the workspace."""
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        if max_bytes < 1 or max_bytes > MAX_WRITE_BYTES:
            raise ValueError(f"max_bytes must be between 1 and {MAX_WRITE_BYTES}")
        payload = content.encode("utf-8")
        if len(payload) > max_bytes:
            raise ValueError("content exceeds max_bytes")

        resolved = self._boundary.resolve(path)
        if any(part in IGNORED_DIRECTORIES for part in Path(resolved.relative_path).parts):
            raise PermissionError("Access to ignored workspace directories is not allowed")
        existed = resolved.absolute_path.exists()
        if existed and not resolved.absolute_path.is_file():
            raise ValueError(f"Not a file: {resolved.relative_path}")
        if existed and not overwrite:
            raise FileExistsError(f"File already exists: {resolved.relative_path}")

        # Resolve the parent before creating it so the parent remains inside
        # the same canonical workspace boundary.
        parent = self._boundary.resolve(resolved.absolute_path.parent, require_exists=False)
        parent.absolute_path.mkdir(parents=True, exist_ok=True)
        resolved.absolute_path.write_bytes(payload)

        operation = "update" if existed else "create"
        event = WorkspaceMutationEvent(operation, resolved.relative_path, len(payload))
        if self._audit_sink is not None:
            self._audit_sink(event)
        return {
            "path": resolved.relative_path,
            "operation": operation,
            "bytes_written": len(payload),
        }

    def delete_file(self, path: str) -> dict[str, object]:
        """Delete one regular file inside the workspace."""
        resolved = self._boundary.resolve(path, require_exists=True, expected_kind="file")
        if any(part in IGNORED_DIRECTORIES for part in Path(resolved.relative_path).parts):
            raise PermissionError("Access to ignored workspace directories is not allowed")
        resolved.absolute_path.unlink()
        event = WorkspaceMutationEvent("delete", resolved.relative_path)
        if self._audit_sink is not None:
            self._audit_sink(event)
        return {"path": resolved.relative_path, "operation": "delete"}
