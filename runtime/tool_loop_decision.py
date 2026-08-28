from __future__ import annotations

import re
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
    verification_reused: bool = False,
) -> ToolLoopDecision:
    """Classify whether a tool result warrants another LLM reasoning turn."""
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
        verification_reused=verification_reused,
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
    verification_reused: bool = False,
) -> bool:
    """Return whether a verification call is sufficient to finish a tool loop.

    The policy is deliberately conservative: only a recognized full-suite
    command that actually ran after a workspace change can terminate the loop.
    Reused evidence never becomes fresh terminal evidence.
    """
    if tool_name != "run_command" or status != "completed" or verification_reused:
        return False
    command = arguments.get("command")
    if not isinstance(command, str):
        return False
    normalized = command.strip().lower()
    if normalized not in TERMINAL_VERIFICATION_COMMANDS:
        return False
    if not changed_files or not _verification_succeeded(str(result)):
        return False
    if not command_results:
        return False
    latest = command_results[-1]
    if not isinstance(latest, dict) or latest.get("command") != command:
        return False
    return _verification_succeeded(str(latest.get("result", "")))


def _verification_succeeded(result: str) -> bool:
    """Recognize positive test evidence without rejecting zero-failure summaries."""
    normalized = result.strip().lower()
    if not normalized:
        return False
    if any(marker in normalized for marker in ("traceback", "assertionerror", "no tests ran")):
        return False

    # Test runners commonly report both positive and zero failure counts, e.g.
    # ``1100 passed, 0 failed``. Only a positive failure/error count is fatal.
    for pattern in (r"\b(\d+)\s+failed\b", r"\b(\d+)\s+failure(?:s)?\b", r"\b(\d+)\s+error(?:s)?\b"):
        if any(int(count) > 0 for count in re.findall(pattern, normalized)):
            return False

    return bool(
        re.search(r"\b\d+\s+passed\b", normalized)
        or re.search(r"\b\d+\s+success(?:es|ful)?\b", normalized)
        or re.search(r"\bok\b", normalized)
    )
