from pathlib import Path

from security.workspace import resolve_workspace_path


IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
}


def list_files(path: str = ".") -> list[str]:
    """List files inside the authorized workspace."""

    root = resolve_workspace_path(path)

    if not root.exists():
        raise FileNotFoundError(
            f"Path not found: {root}"
        )

    if not root.is_dir():
        raise ValueError(
            f"Not a directory: {root}"
        )

    files = []

    for p in root.rglob("*"):

        if not p.is_file():
            continue

        relative = p.relative_to(root)

        if any(
            part in IGNORED_DIRECTORIES
            for part in relative.parts
        ):
            continue

        files.append(str(relative))

    return files


def read_file(path: str) -> str:
    """Read a file inside the authorized workspace."""

    file_path = resolve_workspace_path(path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    if not file_path.is_file():
        raise ValueError(
            f"Not a file: {file_path}"
        )

    return file_path.read_text(
        encoding="utf-8",
        errors="replace",
    )


def write_file(
    path: str,
    content: str,
) -> None:
    """Write a file inside the authorized workspace."""

    file_path = resolve_workspace_path(path)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path.write_text(
        content,
        encoding="utf-8",
    )

def move_file(
    source: str,
    destination: str,
) -> None:
    """Move a file inside the authorized workspace."""

    source_path = resolve_workspace_path(source)
    destination_path = resolve_workspace_path(destination)

    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file not found: {source_path}"
        )

    if not source_path.is_file():
        raise ValueError(
            f"Source is not a file: {source_path}"
        )

    destination_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_path.replace(destination_path)
    
def delete_file(path: str) -> None:
    """Delete a file inside the authorized workspace."""

    file_path = resolve_workspace_path(path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    if not file_path.is_file():
        raise ValueError(
            f"Not a file: {file_path}"
        )

    file_path.unlink()