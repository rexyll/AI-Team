from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

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
    """Host-owned Git boundary for controlled repository collaboration."""

    def __init__(self, sandbox: WorkspaceSandbox | None = None) -> None:
        self._sandbox = sandbox or WorkspaceSandbox()

    def execute(self, request: GitOperationRequest, *, env: Mapping[str, str] | None = None) -> str:
        if not isinstance(request, GitOperationRequest):
            raise TypeError("request must be a GitOperationRequest")

        workspace = self._sandbox.require_directory(request.workspace)
        self._require_repository(workspace, env=env)

        if request.operation == "status":
            return self._git("status --short", workspace, env=env)
        if request.operation == "diff":
            return self._git("diff --cached" if request.staged else "diff", workspace, env=env)
        if request.operation == "log":
            return self._git(f"log --max-count={request.max_count}", workspace, env=env)
        if request.operation == "show":
            return self._git(f"show {self._revision(request.revision)}", workspace, env=env)
        if request.operation == "branch":
            return self._git("branch --list", workspace, env=env)
        if request.operation == "rev-parse":
            return self._git(f"rev-parse {self._revision(request.revision)}", workspace, env=env)
        if request.operation == "add":
            return self._add(request, workspace, env=env)
        if request.operation == "commit":
            return self._commit(request, workspace, env=env)
        raise AssertionError(f"unhandled Git operation: {request.operation}")

    def status(self, workspace: str, *, env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("status", workspace), env=env)

    def diff(self, workspace: str, *, staged: bool = False, env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("diff", workspace, staged=staged), env=env)

    def log(self, workspace: str, *, max_count: int = 20, env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("log", workspace, max_count=max_count), env=env)

    def show(self, workspace: str, *, revision: str = "HEAD", env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("show", workspace, revision=revision), env=env)

    def branch(self, workspace: str, *, env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("branch", workspace), env=env)

    def rev_parse(self, workspace: str, *, revision: str = "HEAD", env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("rev-parse", workspace, revision=revision), env=env)

    def add(self, workspace: str, paths: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("add", workspace, paths=tuple(paths)), env=env)

    def commit(self, workspace: str, message: str, *, env: Mapping[str, str] | None = None) -> str:
        return self.execute(GitOperationRequest("commit", workspace, message=message), env=env)

    def _git(self, command: str, workspace: Path, *, env: Mapping[str, str] | None = None) -> str:
        if env is None:
            return git_tool.git_command(command, str(workspace), sandbox=self._sandbox)
        return git_tool.git_command(command, str(workspace), sandbox=self._sandbox, env=env)

    def _require_repository(self, workspace: Path, *, env: Mapping[str, str] | None = None) -> None:
        result = self._git("rev-parse --show-toplevel", workspace, env=env)
        if not result.startswith("exit_code=0\n"):
            raise ValueError("workspace is not a Git repository")
        lines = result.splitlines()
        root_line = lines[1].strip() if len(lines) > 1 else ""
        if not root_line:
            raise ValueError("Git repository root could not be determined")
        root = self._sandbox.resolve(root_line)
        try:
            workspace.relative_to(root)
        except ValueError as exc:
            raise PermissionError("workspace is outside the Git repository root") from exc

    def _add(self, request: GitOperationRequest, workspace: Path, *, env: Mapping[str, str] | None = None) -> str:
        if not request.paths:
            raise ValueError("add requires at least one path")
        safe_paths: list[str] = []
        for path in request.paths:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = workspace / candidate
            resolved = self._sandbox.resolve(candidate)
            try:
                relative = resolved.relative_to(workspace)
            except ValueError as exc:
                raise PermissionError("Git path is outside the authorized workspace") from exc
            safe_paths.append(str(relative))
        quoted = " ".join(self._quote(path) for path in safe_paths)
        return self._git(f"add {quoted}", workspace, env=env)

    def _commit(self, request: GitOperationRequest, workspace: Path, *, env: Mapping[str, str] | None = None) -> str:
        message = request.message.strip()
        if not message:
            raise ValueError("commit message must be non-empty")
        if "\n" in message or "\r" in message:
            raise ValueError("commit message must be single-line")
        return self._git(f"commit -m {self._quote(message)}", workspace, env=env)

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
