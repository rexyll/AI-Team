"""Dependency policy checks for the AI-Team runtime.

The policy intentionally starts from the repository's requirements.txt instead of
trying to replace a package manager.  It provides a small, deterministic contract
that CI/tests can enforce: every runtime dependency must be explicitly declared,
pinned with an exact version, and appear only once.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(==)([^\s;]+)$")


@dataclass(frozen=True)
class Dependency:
    name: str
    version: str


def parse_requirements(path: str | Path) -> tuple[Dependency, ...]:
    """Parse simple pinned requirements from a requirements file."""
    path = Path(path)
    dependencies: list[Dependency] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQUIREMENT_RE.fullmatch(line)
        if not match:
            raise ValueError(
                f"Unsupported dependency declaration at {path}:{line_number}: {raw!r}. "
                "Dependencies must use exact == pins."
            )
        name = match.group(1).lower()
        if name in seen:
            raise ValueError(f"Duplicate dependency declaration: {name}")
        seen.add(name)
        dependencies.append(Dependency(name=name, version=match.group(3)))
    return tuple(dependencies)


def validate_dependency_policy(path: str | Path) -> tuple[Dependency, ...]:
    """Validate the repository dependency policy and return its dependency set."""
    dependencies = parse_requirements(path)
    if not dependencies:
        raise ValueError("Dependency policy requires at least one declared dependency")
    return dependencies
