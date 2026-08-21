from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "projects"
).resolve()


class WorkspaceSandbox:
    """Resolve filesystem paths while enforcing the authorized workspace root."""

    def __init__(self, root: Path | str = PROJECT_ROOT) -> None:
        self.root = Path(root).resolve()

    def resolve(self, path: str | Path) -> Path:
        if not isinstance(path, (str, Path)):
            raise TypeError(
                "Workspace path must be a string or pathlib.Path"
            )

        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = self.root / candidate

        candidate = candidate.resolve()

        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(
                f"Access denied outside workspace: {candidate}"
            ) from exc

        return candidate

    def require_file(self, path: str | Path) -> Path:
        resolved = self.resolve(path)

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {resolved}")

        if not resolved.is_file():
            raise ValueError(f"Not a file: {resolved}")

        return resolved

    def require_directory(self, path: str | Path) -> Path:
        resolved = self.resolve(path)

        if not resolved.exists():
            raise FileNotFoundError(f"Path not found: {resolved}")

        if not resolved.is_dir():
            raise ValueError(f"Not a directory: {resolved}")

        return resolved


DEFAULT_SANDBOX = WorkspaceSandbox()


def resolve_workspace_path(path: str | Path) -> Path:
    """Resolve a path and ensure it stays inside the authorized workspace."""

    return DEFAULT_SANDBOX.resolve(path)
