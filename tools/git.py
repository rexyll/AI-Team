import shlex
import subprocess

from security.workspace import resolve_workspace_path


ALLOWED_GIT_COMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "add",
    "commit",
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

    subcommand = args[0].lower()
    if subcommand not in ALLOWED_GIT_COMMANDS:
        raise PermissionError(
            f"Git subcommand is not allowed: {subcommand}"
        )

    for token in args:
        normalized = token.strip('"').lower()
        if normalized in BLOCKED_TOKENS:
            raise PermissionError(
                f"Git option is not allowed: {normalized}"
            )

    return args


def git_command(command: str, cwd: str) -> str:
    """Run an allow-listed Git command inside the authorized workspace."""
    working_directory = resolve_workspace_path(cwd)
    args = _parse_git_command(command)

    result = subprocess.run(
        ["git", *args],
        cwd=str(working_directory),
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    return f"exit_code={result.returncode}\n{output}"
