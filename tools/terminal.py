import locale
import subprocess

from security.workspace import resolve_workspace_path


def run_command(
    command: str,
    cwd: str | None = ".",
) -> str:
    """Execute PowerShell command inside the authorized workspace."""

    working_directory = resolve_workspace_path(
        cwd or "."
    )

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=str(working_directory),
        capture_output=True,
        text=False,
    )

    encoding = locale.getpreferredencoding(False)

    stdout = result.stdout.decode(
        encoding,
        errors="replace",
    )

    stderr = result.stderr.decode(
        encoding,
        errors="replace",
    )

    output = stdout

    if stderr:
        output += "\n" + stderr

    return (
        f"exit_code={result.returncode}\n"
        f"{output}"
    )