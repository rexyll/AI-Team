from __future__ import annotations

from typing import Any


EXPLORATION_TOOLS = frozenset({"list_files", "read_file"})
PROGRESS_TOOLS = frozenset({"write_file"})
VERIFICATION_COMMAND_MARKERS = (
    "pytest",
    "unittest",
    "mypy",
    "ruff",
    "pyright",
    "npm test",
    "pnpm test",
    "yarn test",
    "cargo test",
)


def classify_tool_call_category(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    duplicate_of: str | None,
    retry_of: str | None,
) -> str:
    """Return a conservative, observable category for a tool-loop call.

    The classifier deliberately uses only execution metadata available at the
    call boundary. It does not claim semantic equivalence between different
    calls; that remains a future, evidence-backed optimization.
    """
    if retry_of:
        return "failure_recovery"
    if duplicate_of:
        return "exact_duplicate"
    if tool_name in EXPLORATION_TOOLS:
        return "exploration"
    if tool_name == "run_command":
        command = str(arguments.get("command", "")).strip().lower()
        if any(marker in command for marker in VERIFICATION_COMMAND_MARKERS):
            return "verification"
        return "execution"
    if tool_name in PROGRESS_TOOLS:
        return "progress_producing"
    return "other"
