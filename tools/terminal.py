import locale
import re
import subprocess

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


def run_command(
    command: str,
    cwd: str | None = ".",
) -> str:
    """Execute an allow-listed development command inside the workspace."""
    working_directory = resolve_workspace_path(cwd or ".")
    _validate_command(command)

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
