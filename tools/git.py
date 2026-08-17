import subprocess


def git_command(command: str, cwd: str) -> str:
    """Run a git command inside the specified repository."""
    result = subprocess.run(
        f"git {command}",
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