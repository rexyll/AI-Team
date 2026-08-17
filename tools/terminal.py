import subprocess


def run_command(command: str, cwd: str | None = None) -> str:
    """Run a shell command and return stdout/stderr."""
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = result.stdout

    if result.stderr:
        output += "\n" + result.stderr

    return f"exit_code={result.returncode}\n{output}"