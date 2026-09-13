from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "projects"
).resolve()


class WorkspaceSandbox:
    """Resolve filesystem paths while enforcing the authorized workspace root."""

    def __init__(
        self,
        root: Path | str = PROJECT_ROOT,
        *,
        folded_prefix: str | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        # A mandated output directory's parent segments are folded into the
        # sandbox root ("workspace/e2e_artifact" -> root ".../workspace").
        # Models nonetheless keep writing the literal mandated prefix
        # ("workspace/e2e_artifact/...") relative to the already-anchored
        # root, nesting the deliverable one level too deep. Recording the
        # folded prefix lets resolve() strip exactly that redundancy while
        # every other relative path is untouched.
        if folded_prefix is None:
            self.folded_prefix: tuple[str, ...] = ()
        else:
            self.folded_prefix = tuple(
                part.casefold()
                for part in folded_prefix.replace("\\", "/").split("/")
                if part
            )

    def _strip_folded_prefix(self, candidate: Path) -> Path:
        if not self.folded_prefix:
            return candidate
        parts = candidate.parts
        if len(parts) < len(self.folded_prefix):
            return candidate
        head = tuple(part.casefold() for part in parts[: len(self.folded_prefix)])
        if head != self.folded_prefix:
            return candidate
        remainder = parts[len(self.folded_prefix):]
        return Path(*remainder) if remainder else Path(".")

    def resolve(self, path: str | Path) -> Path:
        if not isinstance(path, (str, Path)):
            raise TypeError(
                "Workspace path must be a string or pathlib.Path"
            )

        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = self._strip_folded_prefix(candidate)
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


def set_default_workspace_root(
    root: str | Path,
    *,
    folded_prefix: str | None = None,
) -> Path:
    """Redirect the default sandbox root and return the resolved path.

    Used by the CLI to honor requirement-mandated output directories:
    after redirection, every relative path written through any tool lands
    inside ``root`` by construction - no model cooperation required.

    The anchored root is created eagerly: a mandated root can point at a
    directory that no tool run has created yet, and without it every
    workspace-relative read (list_files on ".") fails before the agents
    can produce anything.

    ``folded_prefix`` is the mandated directory's parent-segment chain
    (e.g. ``"workspace"`` for ``"workspace/e2e_artifact"``): segments that
    anchor_workspace_root folded into the root itself. Relative paths
    starting with it are stripped before resolution, so a model that keeps
    writing the literal mandated prefix still lands in the right place.
    """
    global DEFAULT_SANDBOX
    if not isinstance(root, (str, Path)):
        raise TypeError("root must be a string or pathlib.Path")

    DEFAULT_SANDBOX = WorkspaceSandbox(root, folded_prefix=folded_prefix)
    DEFAULT_SANDBOX.root.mkdir(parents=True, exist_ok=True)
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


def mandated_folded_prefix(mandated_dir: str) -> str | None:
    """Return the parent-segment chain that anchor_workspace_root folded.

    For ``"workspace/e2e_artifact"`` this is ``"workspace"``: the segment
    chain that became part of the sandbox root and is therefore redundant
    (but harmless once stripped) when models write the literal mandated
    path relative to the anchored root. Single-segment mandates fold
    nothing and return None.
    """
    if not isinstance(mandated_dir, str):
        raise TypeError("mandated_dir must be a string")
    parts = [part for part in mandated_dir.replace("\\", "/").split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[:-1])
    return None


def resolve_workspace_path(path: str | Path) -> Path:
    """Resolve a path and ensure it stays inside the authorized workspace."""

    return DEFAULT_SANDBOX.resolve(path)
