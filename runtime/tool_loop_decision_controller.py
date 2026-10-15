from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.tool_loop_decision import ToolLoopDecision, classify_tool_result_for_decision


@dataclass(frozen=True)
class ToolLoopDecisionState:
    """Small state object for integrating decision classification into an agent loop."""

    last_reason: str | None = None
    terminal: bool = False
    decisions: int = 0


class ToolLoopDecisionController:
    """Stateful adapter between tool-loop telemetry and decision policy.

    The controller deliberately does not execute tools or mutate agent messages.
    It provides a narrow integration seam so the live Developer loop can adopt
    decision-turn reduction without duplicating policy logic or accidentally
    treating failures/retries as terminal completion.
    """

    def __init__(self) -> None:
        self._state = ToolLoopDecisionState()

    @property
    def state(self) -> ToolLoopDecisionState:
        return self._state

    def classify(
        self,
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
        )
        self._state = ToolLoopDecisionState(
            last_reason=decision.reason,
            terminal=decision.terminal,
            decisions=self._state.decisions + 1,
        )
        return decision

    def reset(self) -> None:
        self._state = ToolLoopDecisionState()
