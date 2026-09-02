import locale
import re
import subprocess
from pathlib import Path

from security.workspace import resolve_workspace_path


ALLOWED_EXECUTABLES = {
    "python", "python.exe", "pytest", "pytest.exe", "pip", "pip.exe",
    "uv", "uv.exe", "poetry", "poetry.exe", "ruff", "ruff.exe",
    "mypy", "mypy.exe", "node", "node.exe", "npm", "npm.cmd",
    "npx", "npx.cmd", "pnpm", "pnpm.cmd", "yarn", "yarn.cmd",
    "dotnet", "dotnet.exe", "cargo", "cargo.exe", "go", "go.exe",
    "cmake", "cmake.exe", "msbuild", "msbuild.exe",
}

BLOCKED_ARGUMENTS = {
    "-c", "--command", "-command", "-encodedcommand", "-e", "--exec",
}

SHELL_PATTERN = re.compile(r"[&|;<>`]|\$\(|\$\{|\$env:")


def _validate_command(command: str) -> None:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")

    if SHELL_PATTERN.search(command):
        raise PermissionError(
            "Shell chaining, redirection, and expansion are not allowed"
        )

    normalized = command.strip().replace("/", "\\")
    first_token = normalized.split(None, 1)[0].strip('"').lower()
    executable = first_token.rsplit("\\", 1)[-1]

    if executable not in ALLOWED_EXECUTABLES:
        raise PermissionError(
            f"Executable is not allowed by terminal policy: {executable}"
        )

    tokens = normalized.lower().split()
    if any(token.strip('"') in BLOCKED_ARGUMENTS for token in tokens):
        raise PermissionError(
            "Code-evaluation and encoded-command arguments are not allowed"
        )


def _replace_first_token(command: str, executable: str) -> str:
    """Replace only the command's first token while preserving its arguments."""
    leading = command[: len(command) - len(command.lstrip())]
    remainder = command.lstrip()

    if remainder.startswith('"'):
        closing_quote = remainder.find('"', 1)
        if closing_quote == -1:
            return command
        return leading + executable + remainder[closing_quote + 1 :]

    parts = remainder.split(None, 1)
    if len(parts) == 1:
        return leading + executable
    return leading + executable + " " + parts[1]


def _resolve_workspace_executable(command: str, workspace: Path) -> str:
    """Prefer a workspace-local Windows virtualenv executable for bare commands."""
    stripped = command.lstrip()
    if not stripped:
        return command

    first_token = stripped.split(None, 1)[0].strip('"')
    if any(separator in first_token for separator in ("/", "\\", ":")):
        return command

    executable = Path(first_token).name.lower()
    if executable not in ALLOWED_EXECUTABLES:
        return command

    scripts_dir = workspace / ".venv" / "Scripts"
    candidates = [scripts_dir / executable]

    if "." not in executable:
        candidates.extend(
            [
                scripts_dir / f"{executable}.exe",
                scripts_dir / f"{executable}.cmd",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return _replace_first_token(command, str(candidate))

    return command


def run_command(
    command: str,
    cwd: str | None = ".",
) -> str:
    """Execute an allow-listed development command inside the workspace."""
    working_directory = resolve_workspace_path(cwd or ".")
    _validate_command(command)
    command = _resolve_workspace_executable(command, working_directory)

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=str(working_directory),
        capture_output=True,
        text=False,
    )

    encoding = locale.getpreferredencoding(False)
    stdout = result.stdout.decode(encoding, errors="replace")
    stderr = result.stderr.decode(encoding, errors="replace")

    output = stdout
    if stderr:
        output += "\n" + stderr

    return f"exit_code={result.returncode}\n{output}"
