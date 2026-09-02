from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from runtime.host_git import HostGitOperationService
from security.workspace import WorkspaceSandbox

from .sanitization import redact_environment_values, sanitized_environment


DEFAULT_MAX_OUTPUT_CHARS = 64 * 1024
MAX_OUTPUT_CHARS = 512 * 1024

READ_OPERATIONS = frozenset({"status", "diff", "log", "show", "branch", "rev-parse"})
WRITE_OPERATIONS = frozenset({"add", "commit"})
ALLOWED_OPERATIONS = READ_OPERATIONS | WRITE_OPERATIONS


@dataclass(frozen=True)
class MCPGitResult:
    operation: str
    output: str
    truncated: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "output": self.output,
            "truncated": self.truncated,
        }


class MCPGitCapabilityBoundary:
    """MCP-facing Git capability boundary over the host-owned Git service."""

    def __init__(
        self,
        workspace_root: str,
        *,
        service: HostGitOperationService | None = None,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        if not isinstance(max_output_chars, int) or isinstance(max_output_chars, bool):
            raise TypeError("max_output_chars must be an integer")
        if max_output_chars < 1 or max_output_chars > MAX_OUTPUT_CHARS:
            raise ValueError(
                f"max_output_chars must be between 1 and {MAX_OUTPUT_CHARS}"
            )
        self._sandbox = WorkspaceSandbox(workspace_root)
        self._service = service or HostGitOperationService(self._sandbox)
        self._max_output_chars = max_output_chars

    def execute(
        self,
        operation: str,
        *,
        path: str = ".",
        revision: str = "HEAD",
        max_count: int = 20,
        staged: bool = False,
        paths: Sequence[str] = (),
        message: str = "",
    ) -> dict[str, object]:
        if operation not in ALLOWED_OPERATIONS:
            raise PermissionError(f"Git operation is not allowed: {operation!r}")
        workspace = self._resolve_git_workspace(path)

        # Keep the existing host-owned service as the semantic Git boundary,
        # but execute its subprocesses with a credential-free environment.
        child_environment = sanitized_environment()
        if operation == "status":
            raw = self._service.status(str(workspace), env=child_environment)
        elif operation == "diff":
            raw = self._service.diff(str(workspace), staged=staged, env=child_environment)
        elif operation == "log":
            raw = self._service.log(str(workspace), max_count=max_count, env=child_environment)
        elif operation == "show":
            raw = self._service.show(str(workspace), revision=revision, env=child_environment)
        elif operation == "branch":
            raw = self._service.branch(str(workspace), env=child_environment)
        elif operation == "rev-parse":
            raw = self._service.rev_parse(str(workspace), revision=revision, env=child_environment)
        elif operation == "add":
            raw = self._service.add(str(workspace), paths, env=child_environment)
        elif operation == "commit":
            raw = self._service.commit(str(workspace), message, env=child_environment)
        else:
            raise AssertionError(f"unhandled Git operation: {operation}")

        result = self._bounded_result(operation, redact_environment_values(raw, child_environment))
        return result.as_dict()

    def status(self, path: str = ".") -> dict[str, object]:
        return self.execute("status", path=path)

    def diff(self, path: str = ".", *, staged: bool = False) -> dict[str, object]:
        return self.execute("diff", path=path, staged=staged)

    def log(self, path: str = ".", *, max_count: int = 20) -> dict[str, object]:
        return self.execute("log", path=path, max_count=max_count)

    def show(self, path: str = ".", *, revision: str = "HEAD") -> dict[str, object]:
        return self.execute("show", path=path, revision=revision)

    def branch(self, path: str = ".") -> dict[str, object]:
        return self.execute("branch", path=path)

    def rev_parse(self, path: str = ".", *, revision: str = "HEAD") -> dict[str, object]:
        return self.execute("rev-parse", path=path, revision=revision)

    def add(self, path: str, paths: Sequence[str]) -> dict[str, object]:
        return self.execute("add", path=path, paths=paths)

    def commit(self, path: str, message: str) -> dict[str, object]:
        return self.execute("commit", path=path, message=message)

    def _resolve_git_workspace(self, path: str) -> Path:
        workspace = self._sandbox.require_directory(path)
        relative = workspace.relative_to(self._sandbox.root)
        if ".git" in relative.parts:
            raise PermissionError(
                "Direct access to Git metadata is not allowed; "
                "use the host-owned Git boundary"
            )
        return workspace

    def _bounded_result(self, operation: str, raw: str) -> MCPGitResult:
        if len(raw) <= self._max_output_chars:
            return MCPGitResult(operation, raw)
        return MCPGitResult(
            operation,
            raw[: self._max_output_chars],
            truncated=True,
        )
