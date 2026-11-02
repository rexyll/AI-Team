"""Deliverable dependency scan: offline SBOM + declaration audit.

Produces deterministic dependency evidence for the delivery phase:

- an SBOM parsed from the deliverable's ``requirements.txt`` (name, exact
  pin or not);
- third-party imports detected from the source that are NOT declared in
  requirements (stdlib and local modules are filtered);
- an explicit ``unavailable`` record for vulnerability-database lookups:
  the runtime's network egress policy is deny-by-default, so pip-audit is
  never executed silently — the evidence states what was actually checked.

Record-only by design (no gating decision hangs off it in this slice).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

_REQUIREMENT_LINE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)\s*(?P<specifier>.*)$")
_PIN_PREFIX = re.compile(r"^==")
_LOCAL_SUFFIXES = (".py",)


def _parse_requirement_line(line: str) -> tuple[str, str] | None:
    """Return ``(name, specifier)`` for one requirement line, or None."""
    cleaned = line.split("#", 1)[0].strip()
    if not cleaned or cleaned.startswith("-"):  # options like -r/-e/-f
        return None
    cleaned = cleaned.split(";", 1)[0].strip()  # strip environment markers
    if not cleaned:
        return None
    match = _REQUIREMENT_LINE.match(cleaned)
    if match is None:
        return None
    name = match.group("name").strip()
    specifier = match.group("specifier").strip()
    if not name:
        return None
    return name, specifier


def _is_pinned(specifier: str) -> bool:
    return bool(_PIN_PREFIX.match(specifier)) and "*" not in specifier


def _third_party_imports(root: Path) -> set[str]:
    """Top-level module names imported by the deliverable's source."""
    local_tops = {path.stem for path in root.rglob("*.py")}
    local_tops |= {path.name for path in root.rglob("*") if path.is_dir()}
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue  # broken syntax is the static gate's finding, not ours
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    imports.add(node.module.split(".")[0])
    return {
        name
        for name in imports
        if name not in stdlib and name not in local_tops
    }


def scan_deliverable_dependencies(deliverable_root: str | Path) -> dict[str, Any]:
    """Build the dependency SBOM and declaration audit for one deliverable."""
    root = Path(deliverable_root)
    if not root.is_dir():
        return {"status": "skipped", "reason": "deliverable root does not exist"}
    requirements_path = root / "requirements.txt"
    if not requirements_path.is_file():
        return {
            "status": "completed",
            "requirements_file": False,
            "declared": [],
            "unpinned": [],
            "undeclared_imports": [],
            "vulnerability_lookup": {
                "status": "unavailable",
                "reason": "network egress is denied by policy; pip-audit not executed",
            },
        }
    declared: list[str] = []
    unpinned: list[str] = []
    for raw_line in requirements_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = _parse_requirement_line(raw_line)
        if parsed is None:
            continue
        name, specifier = parsed
        declared.append(f"{name}{specifier}")
        if not _is_pinned(specifier):
            unpinned.append(name)
    declared_names = {
        _REQUIREMENT_LINE.match(item).group("name").lower()
        for item in declared
        if _REQUIREMENT_LINE.match(item) is not None
    }
    undeclared = sorted(
        name
        for name in _third_party_imports(root)
        if name.lower() not in declared_names
    )
    return {
        "status": "completed",
        "requirements_file": True,
        "declared": declared,
        "unpinned": unpinned,
        "undeclared_imports": undeclared,
        "vulnerability_lookup": {
            "status": "unavailable",
            "reason": "network egress is denied by policy; pip-audit not executed",
        },
    }
