from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from security.workspace import WorkspaceSandbox
from tools import git as git_tool


GitOperation = Literal[
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "add",
    "commit",
]


@dataclass(frozen=True)
class GitOperationRequest:
    """Host-owned Git request with an explicit operation vocabulary."""

    operation: GitOperation
    workspace: str
    paths: tuple[str, ...] = ()
    revision: str = "HEAD"
    max_count: int = 20
    message: str = ""
    staged: bool = False

    def __post_init__(self) -> None:
        if self.operation not in {
            "status", "diff", "log", "show", "branch", "rev-parse", "add", "commit"
        }:
            raise ValueError(f"Unsupported Git operation: {self.operation!r}")
        if not isinstance(self.workspace, str) or not self.workspace.strip():
            raise ValueError("workspace must be a non-empty string")
        if not isinstance(self.paths, tuple) or any(
            not isinstance(path, str) or not path.strip() for path in self.paths
        ):
            raise ValueError("paths must be a tuple of non-empty strings")
        if not isinstance(self.max_count, int) or isinstance(self.max_count, bool):
            raise TypeError("max_count must be an integer")
        if self.max_count < 1 or self.max_count > 1000:
            raise ValueError("max_count must be between 1 and 1000")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("revision must be a non-empty string")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")


class HostGitOperationService:
    """Host-owned Git boundary for controlled repository collaboration.

    The service exposes semantic Git operations instead of arbitrary Git
    commands. Repository/workspace validation stays on the host side and the
    low-level subprocess helper is not placed in the agent/plugin registry.
    """

    def __init__(self, sandbox: WorkspaceSandbox | None = None) -> None:
        self._sandbox = sandbox or WorkspaceSandbox()

    def execute(self, request: GitOperationRequest) -> str:
        if not isinstance(request, GitOperationRequest):
            raise TypeError("request must be a GitOperationRequest")

        workspace = self._sandbox.require_directory(request.workspace)
        self._require_repository(workspace)

        if request.operation == "status":
            return git_tool.git_command("status --short", str(workspace))
        if request.operation == "diff":
            return git_tool.git_command(
                "diff --cached" if request.staged else "diff", str(workspace)
            )
        if request.operation == "log":
            return git_tool.git_command(
                f"log --max-count={request.max_count}", str(workspace)
            )
        if request.operation == "show":
            return git_tool.git_command(
                f"show {self._revision(request.revision)}", str(workspace)
            )
        if request.operation == "branch":
            return git_tool.git_command("branch --list", str(workspace))
        if request.operation == "rev-parse":
            return git_tool.git_command(
                f"rev-parse {self._revision(request.revision)}", str(workspace)
            )
        if request.operation == "add":
            return self._add(request, workspace)
        if request.operation == "commit":
            return self._commit(request, workspace)
        raise AssertionError(f"unhandled Git operation: {request.operation}")

    def status(self, workspace: str) -> str:
        return self.execute(GitOperationRequest("status", workspace))

    def diff(self, workspace: str, *, staged: bool = False) -> str:
        return self.execute(GitOperationRequest("diff", workspace, staged=staged))

    def log(self, workspace: str, *, max_count: int = 20) -> str:
        return self.execute(GitOperationRequest("log", workspace, max_count=max_count))

    def show(self, workspace: str, *, revision: str = "HEAD") -> str:
        return self.execute(GitOperationRequest("show", workspace, revision=revision))

    def branch(self, workspace: str) -> str:
        return self.execute(GitOperationRequest("branch", workspace))

    def rev_parse(self, workspace: str, *, revision: str = "HEAD") -> str:
        return self.execute(GitOperationRequest("rev-parse", workspace, revision=revision))

    def add(self, workspace: str, paths: Sequence[str]) -> str:
        return self.execute(GitOperationRequest("add", workspace, paths=tuple(paths)))

    def commit(self, workspace: str, message: str) -> str:
        return self.execute(GitOperationRequest("commit", workspace, message=message))

    def _require_repository(self, workspace: Path) -> None:
        result = git_tool.git_command("rev-parse --show-toplevel", str(workspace))
        if not result.startswith("exit_code=0\n"):
            raise ValueError("workspace is not a Git repository")
        lines = result.splitlines()
        root_line = lines[1].strip() if len(lines) > 1 else ""
        if not root_line:
            raise ValueError("Git repository root could not be determined")
        root = self._sandbox.resolve(root_line)
        workspace.relative_to(root)

    def _add(self, request: GitOperationRequest, workspace: Path) -> str:
        if not request.paths:
            raise ValueError("add requires at least one path")
        safe_paths: list[str] = []
        for path in request.paths:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = workspace / candidate
            resolved = self._sandbox.resolve(candidate)
            resolved.relative_to(workspace)
            safe_paths.append(str(resolved.relative_to(workspace)))
        quoted = " ".join(self._quote(path) for path in safe_paths)
        return git_tool.git_command(f"add {quoted}", str(workspace))

    def _commit(self, request: GitOperationRequest, workspace: Path) -> str:
        message = request.message.strip()
        if not message:
            raise ValueError("commit message must be non-empty")
        if "\n" in message or "\r" in message:
            raise ValueError("commit message must be single-line")
        return git_tool.git_command(f"commit -m {self._quote(message)}", str(workspace))

    @staticmethod
    def _revision(revision: str) -> str:
        value = revision.strip()
        if value.startswith("-"):
            raise ValueError("revision must not start with '-'")
        if any(char in value for char in "&|;<>`\n\r"):
            raise ValueError("revision contains forbidden shell characters")
        return value

    @staticmethod
    def _quote(value: str) -> str:
        if '"' in value or "\n" in value or "\r" in value:
            raise ValueError("Git argument contains unsupported quoting characters")
        return f'"{value}"'


DEFAULT_HOST_GIT_SERVICE = HostGitOperationService()
