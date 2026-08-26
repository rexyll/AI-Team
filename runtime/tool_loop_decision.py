from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TERMINAL_VERIFICATION_COMMANDS = frozenset({
    "pytest -q",
    "python -m pytest -q",
    "python -m unittest",
})


@dataclass(frozen=True)
class ToolLoopDecision:
    """Pure classification of whether the next LLM turn needs new reasoning."""

    requires_llm_decision: bool
    reason: str
    terminal: bool = False


def classify_tool_result_for_decision(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    status: str,
    category: str | None = None,
    duplicate_of: str | None = None,
    retry_of: str | None = None,
    changed_files: list[str],
    command_results: list[dict[str, Any]],
) -> ToolLoopDecision:
    """Classify whether a tool result warrants another LLM reasoning turn.

    This is deliberately a policy-only layer. It never executes tools and never
    declares a task successful by itself. Terminal completion remains subject to
    the conservative verification fast-path below; failures and recovery signals
    always retain an LLM decision opportunity.
    """
    if status != "completed":
        return ToolLoopDecision(True, "tool_failure_requires_recovery")
    if retry_of is not None:
        return ToolLoopDecision(True, "retry_requires_reassessment")
    if category == "exact_duplicate" and duplicate_of is not None:
        return ToolLoopDecision(False, "duplicate_evidence_reuse")
    if should_take_terminal_verification_fast_path(
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        status=status,
        changed_files=changed_files,
        command_results=command_results,
    ):
        return ToolLoopDecision(False, "terminal_verification", terminal=True)
    if tool_name == "run_command" and _verification_succeeded(str(result)):
        return ToolLoopDecision(True, "verification_requires_followup_decision")
    return ToolLoopDecision(True, "new_evidence_requires_reasoning")


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
