import shlex
import subprocess
from collections.abc import Mapping

from security.workspace import WorkspaceSandbox, resolve_workspace_path


ALLOWED_GIT_COMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "add",
    "commit",
    "tag",
    "init",
}

BLOCKED_TOKENS = {
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--work-tree",
    "-C",
    "--upload-pack",
    "--receive-pack",
    "--template",
    "--separate-git-dir",
    "--shared",
    "--reference",
    "--reference-if-able",
    "--bare",
    "--object-format",
}

SHELL_METACHARACTERS = {"&", "|", ";", "<", ">", "`"}


def _parse_git_command(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("git command must be a non-empty string")

    if any(char in command for char in SHELL_METACHARACTERS):
        raise PermissionError("Shell metacharacters are not allowed in git commands")

    try:
        args = shlex.split(command, posix=False)
    except ValueError as exc:
        raise ValueError(f"Invalid git command: {exc}") from exc

    if not args:
        raise ValueError("git command must not be empty")

    normalized_args: list[str] = []
    for token in args:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
            token = token[1:-1]
        normalized_args.append(token)

    subcommand = normalized_args[0].lower()
    if subcommand not in ALLOWED_GIT_COMMANDS:
        raise PermissionError(
            f"Git subcommand is not allowed: {subcommand}"
        )

    for token in normalized_args:
        lowered = token.lower()
        # Block both "--flag value" and the inline "--flag=value" spellings.
        candidate = lowered.split("=", 1)[0] if "=" in lowered else lowered
        if lowered in BLOCKED_TOKENS or candidate in BLOCKED_TOKENS:
            raise PermissionError(
                f"Git option is not allowed: {lowered}"
            )

    return normalized_args


def git_command(
    command: str,
    cwd: str,
    *,
    sandbox: WorkspaceSandbox | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Run an allow-listed Git command inside an authorized workspace."""
    working_directory = (
        sandbox.resolve(cwd) if sandbox is not None else resolve_workspace_path(cwd)
    )
    args = _parse_git_command(command)

    result = subprocess.run(
        ["git", *args],
        cwd=str(working_directory),
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(env) if env is not None else None,
    )

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    return f"exit_code={result.returncode}\n{output}"
