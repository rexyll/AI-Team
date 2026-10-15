from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.tool_loop_decision import ToolLoopDecision, classify_tool_result_for_decision


@dataclass(frozen=True)
class DecisionTurnOutcome:
    """Result of classifying one completed tool observation for the loop driver."""

    decision: ToolLoopDecision
    skip_llm_turn: bool
    terminal: bool


def classify_decision_turn(
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
) -> DecisionTurnOutcome:
    """Adapt policy classification into explicit loop-driver actions.

    The loop driver can use ``skip_llm_turn`` to avoid another reasoning call
    only when the policy layer says the observation is safely reusable or
    terminal. Failures and retries always require a fresh decision.
    """
    decision = classify_tool_result_for_decision(
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        status=status,
        category=category,
        duplicate_of=duplicate_of,
        retry_of=retry_of,
        changed_files=changed_files,
        command_results=command_results,
        verification_reused=verification_reused,
    )
    return DecisionTurnOutcome(
        decision=decision,
        skip_llm_turn=not decision.requires_llm_decision,
        terminal=decision.terminal,
    )
