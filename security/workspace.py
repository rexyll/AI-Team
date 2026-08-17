from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "projects"
).resolve()


def resolve_workspace_path(path: str) -> Path:
    """
    Resolve a path and ensure it stays inside projects/.
    """

    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    candidate = candidate.resolve()

    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError:
        raise PermissionError(
            f"Access denied outside workspace: {candidate}"
        )

    return candidate