from __future__ import annotations

from typing import Any


READ_ONLY_VERIFICATION_TOOLS = frozenset({"run_command"})
VERIFICATION_COMMAND_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "unittest",
    "ruff check",
    "mypy",
)


def should_suppress_verification(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    command_results: list[dict[str, Any]],
    changed_files: list[str],
    workspace_revision: int | None = None,
) -> bool:
    """Return whether a safe verification call is already covered by valid evidence.

    A verification result can be reused only for explicitly recognized
    read-only verification commands, after an exact command match and with no
    workspace mutation since that evidence was produced. A monotonic revision
    is preferred because a cumulative changed-file list cannot distinguish a
    mutation that happened before the verification from one that happened
    afterwards.
    """
    if tool_name not in READ_ONLY_VERIFICATION_TOOLS:
        return False
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip() or not _is_verification_command(command):
        return False

    current_files = tuple(dict.fromkeys(str(path) for path in changed_files if path))
    for entry in reversed(command_results):
        if not isinstance(entry, dict) or entry.get("command") != command:
            continue
        result = str(entry.get("result", "")).lower()
        if not _verification_succeeded(result):
            return False

        if workspace_revision is not None and isinstance(entry.get("workspace_revision"), int):
            return entry["workspace_revision"] == workspace_revision

        snapshot = entry.get("changed_files")
        if snapshot is None:
            return not current_files
        if not isinstance(snapshot, (list, tuple, set, frozenset)):
            return False
        recorded_files = tuple(dict.fromkeys(str(path) for path in snapshot if path))
        return recorded_files == current_files
    return False


def record_verification_evidence(
    *,
    command: str,
    result: Any,
    changed_files: list[str],
    workspace_revision: int | None = None,
) -> dict[str, Any]:
    """Create a bounded, mutation-aware verification evidence record."""
    evidence = {
        "command": command,
        "result": str(result),
        "changed_files": list(dict.fromkeys(changed_files)),
    }
    if workspace_revision is not None:
        evidence["workspace_revision"] = workspace_revision
    return evidence


def _is_verification_command(command: str) -> bool:
    normalized = command.strip().lower()
    return any(normalized == prefix or normalized.startswith(prefix + " ") for prefix in VERIFICATION_COMMAND_PREFIXES)


def _verification_succeeded(result: str) -> bool:
    """Recognize positive verification evidence without treating failures as reusable."""
    failure_markers = ("failed", "failure", "error", "traceback", "no tests ran", "assertionerror")
    if any(marker in result for marker in failure_markers):
        return False
    return any(marker in result for marker in ("passed", "pass", "success", "ok"))
