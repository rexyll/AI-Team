from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from security.workspace import WorkspaceSandbox


# Files above the write ceiling cannot be produced by the mutation boundary,
# so optimistic-concurrency hashing is only meaningful at or below it.
MAX_STAT_HASH_BYTES = 8 * 1024 * 1024


IGNORED_DIRECTORIES = frozenset({
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
})
DEFAULT_MAX_READ_BYTES = 512 * 1024
DEFAULT_MAX_SEARCH_RESULTS = 100


@dataclass(frozen=True)
class ResolvedWorkspacePath:
    """A path that has already crossed the canonical workspace boundary."""

    absolute_path: Path
    relative_path: str
    kind: str


class MCPWorkspaceBoundary:
    """MCP adapter over AI-Team's canonical WorkspaceSandbox."""

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
                raise FileNotFoundError(f"Path not found: {self._display(relative)}")
            if expected_kind == "file" and not resolved.is_file():
                raise ValueError(f"Not a file: {self._display(relative)}")
            if expected_kind == "directory" and not resolved.is_dir():
                raise ValueError(f"Not a directory: {self._display(relative)}")

        return ResolvedWorkspacePath(
            absolute_path=resolved,
            relative_path=self._display(relative),
            kind=self._kind(resolved),
        )

    def list_files(self, path: str = ".", *, limit: int = 500) -> list[str]:
        """List authorized files without exposing host absolute paths."""
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        root = self.resolve(path, require_exists=True, expected_kind="directory").absolute_path
        results: list[str] = []
        for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
            relative = candidate.relative_to(self.root)
            if any(part in IGNORED_DIRECTORIES for part in relative.parts):
                continue
            if candidate.is_file():
                results.append(self._display(relative))
                if len(results) >= limit:
                    break
        return results

    def read_file(self, path: str, *, max_bytes: int = DEFAULT_MAX_READ_BYTES) -> str:
        """Read one authorized UTF-8 text file with a bounded payload."""
        if max_bytes < 1 or max_bytes > 8 * 1024 * 1024:
            raise ValueError("max_bytes must be between 1 and 8388608")
        resolved = self.resolve(path, require_exists=True, expected_kind="file")
        if any(part in IGNORED_DIRECTORIES for part in Path(resolved.relative_path).parts):
            raise PermissionError("Access to ignored workspace directories is not allowed")
        if resolved.absolute_path.stat().st_size > max_bytes:
            raise ValueError(f"File exceeds max_bytes: {resolved.relative_path}")
        return resolved.absolute_path.read_text(encoding="utf-8", errors="replace")

    def stat_path(self, path: str = ".") -> dict[str, object]:
        """Return bounded metadata for one authorized workspace path.

        For regular files at or below the write ceiling the payload includes
        the on-disk sha256 so callers can drive the optimistic-concurrency
        write flow without re-deriving hashes from text-mode reads.
        """
        resolved = self.resolve(path, require_exists=True)
        stat = resolved.absolute_path.stat()
        payload: dict[str, object] = {
            "path": resolved.relative_path,
            "kind": resolved.kind,
            "size": stat.st_size if resolved.kind == "file" else 0,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "sha256": None,
        }
        if resolved.kind == "file" and stat.st_size <= MAX_STAT_HASH_BYTES:
            payload["sha256"] = hashlib.sha256(
                resolved.absolute_path.read_bytes()
            ).hexdigest()
        return payload

    def search_text(
        self,
        query: str,
        path: str = ".",
        *,
        max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
        case_sensitive: bool = False,
    ) -> list[dict[str, object]]:
        """Search authorized text files and return bounded relative matches."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if len(query) > 500:
            raise ValueError("query must be at most 500 characters")
        if max_results < 1 or max_results > 1000:
            raise ValueError("max_results must be between 1 and 1000")

        root = self.resolve(path, require_exists=True, expected_kind="directory").absolute_path
        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, object]] = []
        for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
            relative = candidate.relative_to(self.root)
            if any(part in IGNORED_DIRECTORIES for part in relative.parts) or not candidate.is_file():
                continue
            try:
                if candidate.stat().st_size > DEFAULT_MAX_READ_BYTES:
                    continue
                lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.casefold()
                if needle in haystack:
                    matches.append({
                        "path": self._display(relative),
                        "line": line_number,
                        "text": line[:2000],
                    })
                    if len(matches) >= max_results:
                        return matches
        return matches

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
