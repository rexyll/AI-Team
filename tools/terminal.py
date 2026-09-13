import locale
import re
import subprocess
from pathlib import Path
from collections.abc import Mapping

from runtime.tool_errors import ToolExecutionError
from security.process_sandbox import create_process_job
from security.workspace import WorkspaceSandbox, resolve_workspace_path


class TerminalPolicyError(ToolExecutionError, PermissionError):
    """Terminal allow-list violation.

    Inherits ``PermissionError`` so existing security contracts that expect a
    permission-style rejection keep working, and ``ToolExecutionError`` so the
    error boundary preserves this file's own policy text (never traceback or
    arbitrary exception details) as the model-facing denial reason.
    """


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


def _allowed_executable_hint() -> str:
    base_names = sorted(
        name.rsplit(".", 1)[0] if name.endswith((".exe", ".cmd")) else name
        for name in ALLOWED_EXECUTABLES
    )
    return ", ".join(dict.fromkeys(base_names))


def _validate_command(command: str) -> None:
    if not isinstance(command, str) or not command.strip():
        raise TerminalPolicyError("command must be a non-empty string")

    if SHELL_PATTERN.search(command):
        raise TerminalPolicyError(
            "Shell chaining, redirection, and expansion are not allowed. "
            "Write multi-step logic to a .py file with write_file, then run it with python <script>."
        )

    normalized = command.strip().replace("/", "\\")
    first_token = normalized.split(None, 1)[0].strip('"').lower()
    executable = first_token.rsplit("\\", 1)[-1]

    if executable not in ALLOWED_EXECUTABLES:
        raise TerminalPolicyError(
            f"Executable is not allowed by terminal policy: {executable}. "
            f"Allowed executables: {_allowed_executable_hint()}. "
            "Use list_files / read_file / write_file for file operations."
        )

    tokens = normalized.lower().split()
    if any(token.strip('"') in BLOCKED_ARGUMENTS for token in tokens):
        raise TerminalPolicyError(
            "Code-evaluation arguments (e.g. python -c) are not allowed. "
            "Use write_file to create a script file, then run it with python <script>."
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
    *,
    sandbox: WorkspaceSandbox | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Execute an allow-listed development command inside the workspace.

    On Windows the spawned process tree is contained in a Job Object with
    host-configured memory/process ceilings: a timeout terminates the whole
    tree, and kill-on-close sweeps any survivors after the command completes.
    """
    working_directory = (
        sandbox.resolve(cwd or ".") if sandbox is not None else resolve_workspace_path(cwd or ".")
    )
    _validate_command(command)
    command = _resolve_workspace_executable(command, working_directory)

    job = create_process_job()
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=str(working_directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env) if env is not None else None,
        )
        if job is not None:
            job.assign(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if job is not None:
                job.terminate()
            process.wait()
            raise TimeoutError(f"Command timed out after {timeout} seconds") from None
    finally:
        if job is not None:
            job.close()

    encoding = locale.getpreferredencoding(False)
    stdout_text = stdout.decode(encoding, errors="replace")
    stderr_text = stderr.decode(encoding, errors="replace")

    output = stdout_text
    if stderr_text:
        output += "\n" + stderr_text

    return f"exit_code={process.returncode}\n{output}"
