from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from agents.reviewer import ReviewerAgent
from runtime.agent_result import AgentResult
from runtime.llm.provider import ProviderLLM


@dataclass
class ReviewerReliabilityStats:
    """Counters for primary/fallback reviewer execution outcomes."""

    primary_attempts: int = 0
    primary_successes: int = 0
    primary_failures: int = 0
    fallback_attempts: int = 0
    fallback_successes: int = 0
    fallback_failures: int = 0
    empty_responses: int = 0

    def record_primary(self, *, success: bool, empty: bool = False) -> None:
        self.primary_attempts += 1
        if success:
            self.primary_successes += 1
        else:
            self.primary_failures += 1
        if empty:
            self.empty_responses += 1

    def record_fallback(self, *, success: bool, empty: bool = False) -> None:
        self.fallback_attempts += 1
        if success:
            self.fallback_successes += 1
        else:
            self.fallback_failures += 1
        if empty:
            self.empty_responses += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "primary_attempts": self.primary_attempts,
            "primary_successes": self.primary_successes,
            "primary_failures": self.primary_failures,
            "fallback_attempts": self.fallback_attempts,
            "fallback_successes": self.fallback_successes,
            "fallback_failures": self.fallback_failures,
            "empty_responses": self.empty_responses,
        }


class ResilientReviewerAgent:
    """Run the normal reviewer first and recover with an optional fallback model.

    The wrapper deliberately keeps ReviewerAgent unchanged for compatibility.
    A fallback is only activated after the primary reviewer raises (including
    invalid/empty reviewer output). If both paths fail, a conservative
    ``revision`` result is returned instead of turning reviewer infrastructure
    failure into a task execution failure.
    """

    role = "reviewer"

    def __init__(
        self,
        primary: ReviewerAgent,
        fallback: ReviewerAgent | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.stats = ReviewerReliabilityStats()

    def run(self, task) -> AgentResult:
        try:
            result = self.primary.run(task)
            self.stats.record_primary(success=True, empty=not bool(result.message.strip()))
            return self._annotate(result, source="primary")
        except Exception as primary_exc:
            self.stats.record_primary(
                success=False,
                empty=self._looks_empty(primary_exc),
            )

            if self.fallback is not None:
                self.stats.record_fallback(success=False)
                try:
                    result = self.fallback.run(task)
                    self.stats.fallback_successes += 1
                    self.stats.fallback_failures -= 1
                    return self._annotate(
                        result,
                        source="fallback",
                        primary_error=primary_exc,
                    )
                except Exception as fallback_exc:
                    self.stats.fallback_failures += 1
                    return self._recovery_result(task, primary_exc, fallback_exc)

            return self._recovery_result(task, primary_exc, None)

    @staticmethod
    def _looks_empty(exc: Exception) -> bool:
        text = str(exc).lower()
        return "empty response" in text or "invalid decision" in text

    @staticmethod
    def _annotate(
        result: AgentResult,
        *,
        source: str,
        primary_error: Exception | None = None,
    ) -> AgentResult:
        data = dict(result.data)
        data["reviewer_execution"] = {
            "source": source,
            "recovered": source == "fallback",
            "primary_error": str(primary_error) if primary_error else None,
        }
        return AgentResult(
            status=result.status,
            agent=result.agent,
            task_id=result.task_id,
            message=result.message,
            data=data,
        )

    @staticmethod
    def _recovery_result(task, primary_error: Exception, fallback_error: Exception | None) -> AgentResult:
        return AgentResult(
            status="revision",
            agent="reviewer",
            task_id=task.id,
            message=(
                "REVISION_REQUIRED\n"
                "Reviewer execution did not produce a reliable quality-gate verdict. "
                "The workflow should retry reviewer execution before treating the task as failed."
            ),
            data={
                "reviewer_execution": {
                    "source": "recovery",
                    "recovered": False,
                    "primary_error": str(primary_error),
                    "fallback_error": str(fallback_error) if fallback_error else None,
                },
            },
        )


def create_reviewer_with_fallback(config, primary_llm: ProviderLLM) -> ResilientReviewerAgent:
    primary = ReviewerAgent(config, llm=primary_llm)
    provider_name = os.getenv("REVIEWER_FALLBACK_PROVIDER", "").strip()
    model_id = os.getenv("REVIEWER_FALLBACK_MODEL", "").strip()
    fallback = None
    if provider_name and model_id:
        fallback = ReviewerAgent(
            config,
            llm=ProviderLLM(model=model_id, provider_profile=provider_name),
        )
    return ResilientReviewerAgent(primary, fallback=fallback)
