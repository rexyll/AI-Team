from __future__ import annotations

import os
from dataclasses import dataclass

from agents.reviewer import ReviewerAgent
from runtime.agent_result import AgentResult
from runtime.context_view import context_view
from runtime.llm.provider import ProviderLLM


FALLBACK_SYSTEM_PROMPT = """
你是可靠性优先的软件 Reviewer 兜底模型。
只做最小质量门禁判断，不展开长篇分析。
第一行必须严格是 APPROVED 或 REVISION_REQUIRED。
只依据任务要求、Developer 的关键交付证据和 Tester 结论判断。
无法确认时必须选择 REVISION_REQUIRED。
""".strip()


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
    """Run the normal reviewer first and recover with an optional fallback model."""

    role = "reviewer"

    def __init__(self, primary: ReviewerAgent, fallback: ReviewerAgent | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.stats = ReviewerReliabilityStats()

    def run(self, task) -> AgentResult:
        try:
            result = self.primary.run(task)
            self.stats.record_primary(success=True, empty=not bool(result.message.strip()))
            return self._annotate(result, source="primary")
        except Exception as primary_exc:
            self.stats.record_primary(success=False, empty=self._looks_empty(primary_exc))

            if self.fallback is not None:
                try:
                    result = self._run_lightweight_fallback(task)
                except Exception as fallback_exc:
                    self.stats.record_fallback(
                        success=False,
                        empty=self._looks_empty(fallback_exc),
                    )
                    return self._recovery_result(task, primary_exc, fallback_exc)

                self.stats.record_fallback(success=True, empty=not bool(result.message.strip()))
                return self._annotate(
                    result,
                    source="fallback",
                    primary_error=primary_exc,
                )

            return self._recovery_result(task, primary_exc, None)

    def _run_lightweight_fallback(self, task) -> AgentResult:
        context = self.fallback.build_context(task)
        view = context_view(context, "reviewer")
        developer_result = view["task_result"]
        tester_feedback = view["tester_feedback"]

        prompt = (
            "请对下面任务做最小质量门禁判断。\n\n"
            f"Task: {view['task_id']}\n"
            f"Title: {view['task_title']}\n"
            f"Requirement: {view['task_description']}\n\n"
            f"Files changed: {self._compact(developer_result, 'files_changed')}\n"
            f"Developer tests: {self._compact(developer_result, 'tests')}\n"
            f"Validation: {self._compact(developer_result, 'validation')}\n"
            f"Tester result: {self._bounded(tester_feedback, 3000)}\n\n"
            "如果证据不足，返回 REVISION_REQUIRED。"
        )
        content = self.fallback.llm.generate(
            prompt,
            system_prompt=FALLBACK_SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=512,
        )
        decision = ReviewerAgent._parse_review_result(content)
        data = ReviewerAgent._build_result_data(
            content=content,
            decision=decision,
            context=context,
        )
        return AgentResult(
            status=decision,
            agent="reviewer",
            task_id=view["task_id"],
            message=content,
            data=data,
        )

    @staticmethod
    def _compact(result, key: str) -> str:
        if not isinstance(result, dict):
            return "[]"
        data = result.get("data", result)
        if not isinstance(data, dict):
            return "[]"
        return ResilientReviewerAgent._bounded(data.get(key, []), 2000)

    @staticmethod
    def _bounded(value, limit: int) -> str:
        text = value if isinstance(value, str) else str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + "...[truncated]"

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
    def _recovery_result(
        task,
        primary_error: Exception,
        fallback_error: Exception | None,
    ) -> AgentResult:
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
