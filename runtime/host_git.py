from __future__ import annotations

import os
import re
import subprocess
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
    "init",
    "tag",
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
            "status", "diff", "log", "show", "branch", "rev-parse", "add", "commit",
            "init", "tag",
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
        if request.operation != "init":
            # Only the release anchor may create a repository; every other
            # semantic operation requires an existing one.
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
        if request.operation == "init":
            return self._git("init", workspace, env=env)
        if request.operation == "tag":
            return self._tag(request, workspace, env=env)
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

    def is_repository(self, workspace: str, *, env: Mapping[str, str] | None = None) -> bool:
        """Check whether the workspace is inside an existing Git repository."""
        try:
            self._require_repository(self._sandbox.require_directory(workspace), env=env)
        except ValueError:
            return False
        return True

    def init(self, workspace: str, *, env: Mapping[str, str] | None = None) -> str:
        """Create a Git repository in the workspace (release-anchor semantics)."""
        return self.execute(GitOperationRequest("init", workspace), env=env)

    def tag(
        self,
        workspace: str,
        name: str,
        *,
        message: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Create a lightweight or annotated tag on HEAD."""
        return self.execute(
            GitOperationRequest("tag", workspace, message=message or "", revision=name), env=env
        )

    def head_commit(self, workspace: str, *, env: Mapping[str, str] | None = None) -> str:
        """Return the HEAD commit SHA."""
        result = self.execute(GitOperationRequest("rev-parse", workspace, revision="HEAD"), env=env)
        if not result.startswith("exit_code=0\n"):
            raise ValueError("HEAD commit SHA is unavailable")
        lines = result.splitlines()
        if len(lines) < 2 or not lines[1].strip():
            raise ValueError("HEAD commit SHA could not be parsed")
        return lines[1].strip()

    def remote_url(
        self, workspace: str, *, remote: str = "origin", env: Mapping[str, str] | None = None
    ) -> str:
        """Read the configured host-owned remote URL without exposing credentials."""
        if remote != "origin":
            raise ValueError("only the origin remote is supported")
        root = self._sandbox.require_directory(workspace)
        self._require_repository(root, env=env)
        # Resolve the effective push URL(s), not just the fetch URL: Git
        # permits remote.<name>.pushurl and pushInsteadOf to redirect writes.
        output = self._git_host(
            ["remote", "get-url", "--push", "--all", "origin"], root, env=env
        )
        if not output.startswith("exit_code=0\n"):
            raise RuntimeError("unable to resolve origin push URL")
        urls = [
            line.strip()
            for line in output.split("\n", 1)[1].splitlines()
            if line.strip()
        ]
        if len(urls) != 1:
            raise RuntimeError("origin must resolve to exactly one push destination")
        return urls[0]

    @staticmethod
    def _reject_git_config_environment_overrides(
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Reject command-scope Git config injected through the process environment."""
        effective_env = {**os.environ, **dict(env or {})}
        injected = [
            key
            for key in effective_env
            if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
            or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_\d+", key)
        ]
        if injected:
            raise PermissionError(
                "Git command/environment config overrides are not allowed for host push"
            )

    def _reject_repository_scoped_credential_helpers(
        self, workspace: Path, *, env: Mapping[str, str] | None = None
    ) -> None:
        """Reject credential helpers and config includes owned by the repository.

        Git credential helpers can execute arbitrary programs (including shell
        snippets). Repository-local and worktree config is untrusted input; a
        repository-local include can inject the same setting indirectly. Host-
        level credential helpers remain available for normal authentication.
        """
        helper_pattern = r"^credential(\..*)?\.helper$"
        include_pattern = r"^include(if)?\..*"
        for scope in ("--local", "--worktree"):
            helper_config = self._git_host(
                ["config", scope, "--get-regexp", helper_pattern],
                workspace,
                env=env,
                clean_git_config_environment=True,
            )
            if helper_config.startswith("exit_code=0\n"):
                raise PermissionError(
                    "repository-scoped Git credential helpers are not allowed for host push"
                )
            if helper_config != "exit_code=1\n":
                raise RuntimeError("unable to verify repository-scoped Git credential helpers")

            include_config = self._git_host(
                ["config", scope, "--get-regexp", include_pattern],
                workspace,
                env=env,
                clean_git_config_environment=True,
            )
            if include_config.startswith("exit_code=0\n"):
                raise PermissionError(
                    "repository-scoped Git config includes are not allowed for host push"
                )
            if include_config != "exit_code=1\n":
                raise RuntimeError("unable to verify repository-scoped Git config includes")

    def push(
        self,
        workspace: str,
        *,
        branch: str,
        commit_sha: str,
        expected_remote_url: str,
        remote: str = "origin",
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Push an approved SHA to the exact, revalidated origin destination."""
        if remote != "origin":
            raise ValueError("only the origin remote is supported")
        if (
            not isinstance(expected_remote_url, str)
            or not expected_remote_url
            or expected_remote_url != expected_remote_url.strip()
        ):
            raise ValueError("expected_remote_url must be a non-empty canonical URL")
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
            raise ValueError("commit_sha must be a hexadecimal SHA")
        if (
            not isinstance(branch, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch)
            or branch.endswith((".", "/"))
            or "//" in branch
            or ".." in branch
            or "@{" in branch
            or any(part in {"", ".", ".."} for part in branch.split("/"))
        ):
            raise ValueError("branch name is invalid")
        root = self._sandbox.require_directory(workspace)
        self._require_repository(root, env=env)
        # Repository/worktree credential helpers can execute arbitrary code;
        # local includes can inject them indirectly. Keep credential helpers
        # under host-level configuration only.
        self._reject_repository_scoped_credential_helpers(root, env=None)
        # URL rewrite rules from system, global, local, included and
        # GIT_CONFIG_COUNT scopes can transform even a literal destination.
        # Inspect every effective Git config scope and fail closed on any rule.
        rewrite_config = self._git_host(
            [
                "config", "--get-regexp",
                r"^url\..*\.(insteadOf|pushInsteadOf)$",
            ],
            root,
            env=env,
        )
        if rewrite_config.startswith("exit_code=0\n"):
            raise PermissionError("Git URL rewrite rules are not allowed for host push")
        if rewrite_config != "exit_code=1\n":
            raise RuntimeError("unable to verify Git URL rewrite configuration")
        # The caller environment can inject credential helpers using Git's
        # command-scope config variables; reject all such overrides after the
        # URL rewrite check has had a chance to report a more specific denial.
        self._reject_git_config_environment_overrides(env)
        # Re-resolve the effective push URL immediately before transport. The
        # provider's earlier repository check must not authorize a destination
        # that changed while HEAD was being inspected.
        current_remote_url = self.remote_url(str(root), env=env)
        if current_remote_url != expected_remote_url:
            raise PermissionError("origin push destination changed after approval")
        push_env = dict(env or {})
        # A repository-local core.sshCommand can execute an arbitrary program.
        # GIT_SSH_COMMAND has higher precedence, so pin the host-owned OpenSSH
        # client and prevent interactive password/passphrase prompts.
        push_env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
        push_env["GIT_SSH_VARIANT"] = "ssh"
        return self._git_host(
            [
                "push",
                "--porcelain",
                "--no-verify",
                "--no-follow-tags",
                "--no-recurse-submodules",
                "--receive-pack=git-receive-pack",
                expected_remote_url,
                f"{commit_sha}:refs/heads/{branch}",
            ],
            root,
            env=push_env,
        )

    def _git_host(
        self,
        arguments: list[str],
        workspace: Path,
        *,
        env: Mapping[str, str] | None = None,
        clean_git_config_environment: bool = False,
    ) -> str:
        """Execute a fixed host-owned Git argument vector outside the Agent parser."""
        process_env = {**os.environ, **dict(env or {})}
        if clean_git_config_environment:
            for key in tuple(process_env):
                if (
                    key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
                    or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_\d+", key)
                ):
                    process_env.pop(key, None)
        process_env["GIT_TERMINAL_PROMPT"] = "0"
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(workspace),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=process_env,
            timeout=60,
        )
        output = completed.stdout or ""
        if completed.stderr:
            output += "\n" + completed.stderr
        return f"exit_code={completed.returncode}\n{output}"

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

    def _tag(self, request: GitOperationRequest, workspace: Path, *, env: Mapping[str, str] | None = None) -> str:
        name = self._validate_tag_name(request.revision)
        message = request.message.strip()
        if message:
            if "\n" in message or "\r" in message:
                raise ValueError("tag message must be single-line")
            return self._git(
                f"tag -a {self._quote(name)} -m {self._quote(message)}", workspace, env=env
            )
        return self._git(f"tag {self._quote(name)}", workspace, env=env)

    @staticmethod
    def _validate_tag_name(name: str) -> str:
        value = name.strip()
        if not value:
            raise ValueError("tag name must be non-empty")
        if value.startswith("-"):
            raise ValueError("tag name must not start with '-'")
        forbidden = set("&|;<>`~^:?*[]\\\"'") | {"\n", "\r", "\t", " "}
        if any(char in forbidden for char in value):
            raise ValueError(f"tag name contains forbidden characters: {value!r}")
        if ".." in value or value.endswith("."):
            raise ValueError(f"tag name contains an invalid dot sequence: {value!r}")
        if value.startswith("/") or value.endswith("/") or "//" in value:
            raise ValueError(f"tag name contains an invalid slash sequence: {value!r}")
        return value

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
