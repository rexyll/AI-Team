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


def set_default_workspace_root(root: str | Path) -> Path:
    """Redirect the default sandbox root and return the resolved path.

    Used by the CLI to honor requirement-mandated output directories:
    after redirection, every relative path written through any tool lands
    inside ``root`` by construction - no model cooperation required.
    """
    global DEFAULT_SANDBOX
    if not isinstance(root, (str, Path)):
        raise TypeError("root must be a string or pathlib.Path")

    DEFAULT_SANDBOX = WorkspaceSandbox(root)
    return DEFAULT_SANDBOX.root


def get_default_workspace_root() -> Path:
    """Return the current sandbox root (dynamic read for observability)."""
    return DEFAULT_SANDBOX.root


def anchor_workspace_root(base: str | Path, mandated_dir: str) -> Path:
    """Return the sandbox root that anchors a mandated output directory.

    Rule: keep every segment of ``mandated_dir`` *except the last one* as
    directories under ``base``; the last segment is expected to be created
    by the agents themselves as they write files (e.g. a package named
    like the directory). This preserves the mandated nesting while letting
    natural relative paths land in the right place:

        anchor(base, "workspace/stringkit") -> base/workspace
        anchor(base, "a/b/c")               -> base/a
        anchor(base, "output")              -> base   (single segment)
    """
    if not isinstance(mandated_dir, str):
        raise TypeError("mandated_dir must be a string")

    parts = [part for part in mandated_dir.replace("\\", "/").split("/") if part]
    if len(parts) >= 2:
        return Path(base) / "/".join(parts[:-1])
    return Path(base)


def resolve_workspace_path(path: str | Path) -> Path:
    """Resolve a path and ensure it stays inside the authorized workspace."""

    return DEFAULT_SANDBOX.resolve(path)
