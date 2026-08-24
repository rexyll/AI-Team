"""Deterministic enforcement of explicit path constraints from requirements.

Real-provider runs repeatedly showed plans ignoring requirement-level path
constraints ("所有文件放在 workspace/stringkit/ 目录下"): the model wrote the
code correctly but dropped the directory prefix. Prompt guidance alone did
not close the gap, so the planner now applies a mechanical guarantee: path
tokens are extracted from the requirement text, checked against the parsed
plan, and - when missing - injected into every task description.

The functions here are pure text/dict processors with no I/O and no agent
dependencies, so they are unit-testable in isolation.
"""

from __future__ import annotations

import re


# A relative path token: a name followed by at least one "/" segment chain,
# where a trailing "/" may terminate the token ("src/", "workspace/pkg/").
# Segment bodies allow "*" so a lone trailing slash counts ("src/"); a
# leading lookbehind rejects URLs ("://") and nested mid-token matches.
_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_/:.])[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_.\-]*)+/?"
)

_CONSTRAINT_MARKER = "【用户约束】"


def extract_required_paths(requirement: str) -> list[str]:
    """Extract directory-style path constraints from a requirement.

    Only directory-shaped tokens survive (the last segment must not look
    like a filename with an extension); file specifications such as
    ``stringkit/utils.py`` are already concrete enough to reach task
    descriptions verbatim and must not be turned into directory mandates.

    Returns de-duplicated, order-stable, lower-case-normalized segments
    joined back with "/" (trailing slashes stripped).
    """
    if not isinstance(requirement, str):
        raise TypeError("requirement must be a string")

    found: list[str] = []
    seen: set[str] = set()

    for match in _PATH_TOKEN.finditer(requirement):
        raw = match.group(0).rstrip("/")

        # Empty middle segments ("a//b") are malformed path noise.
        if "//" in raw:
            continue

        last_segment = raw.rsplit("/", 1)[-1]
        # Directory-style only: last segment carries no extension dot.
        if "." in last_segment:
            continue

        normalized = raw.replace("\\", "/").lower()
        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        found.append(normalized)

    return found


def apply_path_constraints(plan: dict, required_dirs: list[str]) -> list[str]:
    """Inject missing directory constraints into every task description.

    The check is **per task**: a directory counts as covered only when it
    appears in *that task's* description. Plan-wide mentions (e.g. the
    model copying the requirement sentence into a single architect task)
    do NOT cover other tasks - real-provider runs showed exactly that
    failure mode, where one task echoed the constraint while developers
    wrote elsewhere.

    Returns the list of directories for which at least one task received
    an injected constraint line.
    """
    if not isinstance(plan, dict):
        raise TypeError("plan must be a dictionary")
    if not isinstance(required_dirs, list) or not all(
        isinstance(item, str) and item.strip() for item in required_dirs
    ):
        raise TypeError("required_dirs must be a list of non-empty strings")

    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return []

    injected: list[str] = []

    for directory in required_dirs:
        key = directory.lower()
        updated_tasks = 0

        for task in tasks:
            description = str(task.get("description", ""))
            if key in description.lower():
                continue

            constraint_line = (
                f"{_CONSTRAINT_MARKER}所有文件必须放在 {directory}/ 目录下。"
            )
            separator = "\n" if description.rstrip() else ""
            task["description"] = (
                f"{description.rstrip()}{separator}{constraint_line}"
            )
            updated_tasks += 1

        if updated_tasks:
            injected.append(directory)

    return injected
