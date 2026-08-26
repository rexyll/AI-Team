from __future__ import annotations

from typing import Any


TERMINAL_VERIFICATION_COMMANDS = frozenset({
    "pytest -q",
    "python -m pytest -q",
    "python -m unittest",
})


def should_take_terminal_verification_fast_path(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    status: str,
    changed_files: list[str],
    command_results: list[dict[str, Any]],
) -> bool:
    """Return whether a verification call is sufficient to finish a tool loop.

    This policy is deliberately conservative. It only applies to a successful,
    explicitly recognized full-suite verification command that ran after at
    least one workspace change. A narrow test, failed command, non-verification
    command, or a command followed by another recorded action is not terminal.

    The helper is pure so the policy can be tested independently before it is
    wired into the live Developer loop.
    """
    if tool_name != "run_command" or status != "completed":
        return False
    command = arguments.get("command")
    if not isinstance(command, str):
        return False
    normalized = command.strip().lower()
    if normalized not in TERMINAL_VERIFICATION_COMMANDS:
        return False
    if not changed_files:
        return False
    if not _verification_succeeded(str(result)):
        return False
    if not command_results:
        return False
    latest = command_results[-1]
    if not isinstance(latest, dict) or latest.get("command") != command:
        return False
    return _verification_succeeded(str(latest.get("result", "")))


def _verification_succeeded(result: str) -> bool:
    normalized = result.strip().lower()
    if not normalized:
        return False
    failure_markers = (
        "failed",
        "failure",
        "error",
        "traceback",
        "no tests ran",
        "assertionerror",
    )
    if any(marker in normalized for marker in failure_markers):
        return False
    return any(marker in normalized for marker in ("passed", "pass", "success", "ok"))
