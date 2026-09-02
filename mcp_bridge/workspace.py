from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from security.workspace import WorkspaceSandbox


@dataclass(frozen=True)
class ResolvedWorkspacePath:
    """A path that has already crossed the canonical workspace boundary."""

    absolute_path: Path
    relative_path: str
    kind: str


class MCPWorkspaceBoundary:
    """MCP adapter over AI-Team's canonical WorkspaceSandbox.

    This class intentionally does not implement its own path-containment
    algorithm. WorkspaceSandbox remains the source of truth.

    MCP adds one stricter adapter-level rule: direct access to Git metadata
    is denied. Git access must go through runtime.host_git instead.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self._sandbox = WorkspaceSandbox(workspace_root)
        self.root = self._sandbox.root

    def resolve(
        self,
        path: str | Path = ".",
        *,
        require_exists: bool = False,
        expected_kind: str | None = None,
        allow_git_metadata: bool = False,
    ) -> ResolvedWorkspacePath:
        resolved = self._sandbox.resolve(path)
        relative = resolved.relative_to(self.root)

        if not allow_git_metadata and ".git" in relative.parts:
            raise PermissionError(
                "Direct access to Git metadata is not allowed; "
                "use the host-owned Git boundary"
            )

        if require_exists and not resolved.exists():
            raise FileNotFoundError(f"Path not found: {self._display(relative)}")

        if expected_kind is not None:
            if expected_kind not in {"file", "directory"}:
                raise ValueError("expected_kind must be 'file', 'directory', or None")
            if not resolved.exists():
                raise FileNotFoundError(
                    f"Path not found: {self._display(relative)}"
                )
            if expected_kind == "file" and not resolved.is_file():
                raise ValueError(f"Not a file: {self._display(relative)}")
            if expected_kind == "directory" and not resolved.is_dir():
                raise ValueError(f"Not a directory: {self._display(relative)}")

        kind = self._kind(resolved)
        return ResolvedWorkspacePath(
            absolute_path=resolved,
            relative_path=self._display(relative),
            kind=kind,
        )

    @staticmethod
    def _display(relative: Path) -> str:
        text = relative.as_posix()
        return "." if text in {"", "."} else text

    @staticmethod
    def _kind(path: Path) -> str:
        if not path.exists():
            return "missing"
        if path.is_file():
            return "file"
        if path.is_dir():
            return "directory"
        return "other"
