from __future__ import annotations

from typing import Any


READ_ONLY_VERIFICATION_TOOLS = frozenset({"run_command"})


def should_suppress_verification(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    command_results: list[dict[str, Any]],
    changed_files: list[str],
) -> bool:
    """Return whether a verification call is already covered by valid evidence.

    Verification evidence is reusable only when the exact command was already
    executed successfully and the workspace has not changed since that result.
    The helper is intentionally conservative: failed/unknown results never
    suppress a retry, and non-verification tools are never suppressed.

    ``command_results`` may optionally contain ``changed_files`` snapshots. New
    callers should record the snapshot when the command completes; legacy
    entries without a snapshot remain reusable only when there have been no
    known changed files at all.
    """
    if tool_name not in READ_ONLY_VERIFICATION_TOOLS:
        return False
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        return False

    current_files = tuple(dict.fromkeys(str(path) for path in changed_files if path))
    for entry in reversed(command_results):
        if not isinstance(entry, dict) or entry.get("command") != command:
            continue
        result = str(entry.get("result", "")).lower()
        if not _verification_succeeded(result):
            return False
        snapshot = entry.get("changed_files")
        if snapshot is None:
            return not current_files
        recorded_files = tuple(dict.fromkeys(str(path) for path in snapshot if path)) if isinstance(snapshot, (list, tuple, set, frozenset)) else None
        if recorded_files is None:
            return False
        return recorded_files == current_files
    return False


def record_verification_evidence(
    *,
    command: str,
    result: Any,
    changed_files: list[str],
) -> dict[str, Any]:
    """Create a bounded, mutation-aware verification evidence record."""
    return {
        "command": command,
        "result": str(result),
        "changed_files": list(dict.fromkeys(changed_files)),
    }


def _verification_succeeded(result: str) -> bool:
    """Recognize positive verification evidence without treating failures as reusable."""
    failure_markers = ("failed", "failure", "error", "traceback", "no tests ran", "assertionerror")
    if any(marker in result for marker in failure_markers):
        return False
    return any(marker in result for marker in ("passed", "pass", "success", "ok"))
