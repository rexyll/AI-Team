from pathlib import Path


def read_file(path: str) -> str:
    """Read a text file and return its contents."""
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise ValueError(f"Not a file: {file_path}")

    return file_path.read_text(encoding="utf-8")

from pathlib import Path


def write_file(path: str, content: str) -> None:
    """Write text content to a file."""
    file_path = Path(path)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
