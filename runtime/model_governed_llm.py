from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from runtime.llm.base import BaseLLM, LLMResponse
from runtime.llm.circuit_breaker import RouteCircuitBreaker
from runtime.metrics import MetricsRegistry
from runtime.model_governance import (
    ModelAdmissionDecision,
    ModelGovernance,
    ModelRoute,
    ModelUsage,
)
from runtime.model_usage import ModelUsageLedger
from runtime.context_compaction import estimate_tokens


class ModelAdmissionError(RuntimeError):
    """Raised when project model governance rejects an LLM invocation."""

    def __init__(self, decision: ModelAdmissionDecision) -> None:
        if decision.admitted:
            raise ValueError("ModelAdmissionError requires a rejected decision")
        self.decision = decision
        super().__init__(decision.reason or "model invocation rejected by governance")


class ModelGovernedLLM(BaseLLM):
    """Apply project model admission before delegating to a selected LLM route.

    This is a thin policy adapter, not a second LLM runtime. The wrapped
    ``BaseLLM`` instances remain responsible for provider execution and, when
    configured, actual usage attribution through ``ModelUsageLedger``.
    """

    def __init__(
        self,
        *,
        project_id: str,
        governance: ModelGovernance,
        usage_ledger: ModelUsageLedger,
        routes: Mapping[ModelRoute, BaseLLM],
        primary_healthy: bool | Callable[[], bool] = True,
        estimated_output_tokens: int = 4096,
        metrics: MetricsRegistry | None = None,
        circuit_breaker: RouteCircuitBreaker | None = None,
        primary_route: ModelRoute | None = None,
    ) -> None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if not isinstance(governance, ModelGovernance):
            raise TypeError("governance must be a ModelGovernance")
        if not isinstance(usage_ledger, ModelUsageLedger):
            raise TypeError("usage_ledger must be a ModelUsageLedger")
        if not isinstance(routes, Mapping) or not routes:
            raise ValueError("routes must be a non-empty mapping")
        normalized: dict[ModelRoute, BaseLLM] = {}
        for route, llm in routes.items():
            if not isinstance(route, ModelRoute):
                raise TypeError("all route keys must be ModelRoute instances")
            if not isinstance(llm, BaseLLM):
                raise TypeError("all route values must implement BaseLLM")
            normalized[route] = llm
        if isinstance(estimated_output_tokens, bool) or not isinstance(estimated_output_tokens, int):
            raise TypeError("estimated_output_tokens must be an integer")
        if estimated_output_tokens < 0:
            raise ValueError("estimated_output_tokens must be >= 0")
        if not isinstance(primary_healthy, (bool, Callable)):
            raise TypeError("primary_healthy must be a bool or callable")
        if metrics is not None and not isinstance(metrics, MetricsRegistry):
            raise TypeError("metrics must be a MetricsRegistry or None")
        if circuit_breaker is not None and not isinstance(circuit_breaker, RouteCircuitBreaker):
            raise TypeError("circuit_breaker must be a RouteCircuitBreaker or None")
        if circuit_breaker is not None:
            if primary_route is None:
                raise ValueError("primary_route is required when circuit_breaker is supplied")
            if primary_route not in normalized:
                raise ValueError("primary_route must be one of the configured routes")
        elif primary_route is not None:
            raise ValueError("primary_route is only valid together with circuit_breaker")

        self.project_id = project_id.strip()
        self.governance = governance
        self.usage_ledger = usage_ledger
        self.routes = dict(normalized)
        self.primary_healthy = primary_healthy
        self.estimated_output_tokens = estimated_output_tokens
        self.metrics = metrics
        self.circuit_breaker = circuit_breaker
        self.primary_route = primary_route

    def _primary_health(self) -> bool:
        if self.circuit_breaker is not None:
            return self.circuit_breaker.is_healthy(self.primary_route)
        if callable(self.primary_healthy):
            return bool(self.primary_healthy())
        return self.primary_healthy

    def _record_metric(self, name: str) -> None:
        if self.metrics is not None:
            self.metrics.inc(name)

    def _admit(self, request: ModelUsage) -> tuple[ModelRoute, BaseLLM]:
        decision = self.governance.decide(
            self.project_id,
            usage=self.usage_ledger.usage_for(self.project_id),
            request=request,
            primary_healthy=self._primary_health(),
        )
        if not decision.admitted or decision.route is None:
            self._record_metric("model_governance_admission_rejected_total")
            raise ModelAdmissionError(decision)
        if decision.reason == "primary route unhealthy; fallback selected":
            self._record_metric("model_governance_fallback_selected_total")
        try:
            return decision.route, self.routes[decision.route]
        except KeyError as exc:
            self._record_metric("model_governance_admission_rejected_total")
            raise ModelAdmissionError(
                ModelAdmissionDecision(
                    admitted=False,
                    route=None,
                    reason=f"governance selected an unconfigured route: {decision.route.provider}/{decision.route.model}",
                )
            ) from exc

    def _execute(self, llm: BaseLLM, route: ModelRoute, run: Callable[[], Any]) -> Any:
        """Run one provider call, feeding route health to the circuit breaker.

        The breaker observes execution outcomes but never changes them: a
        failure is recorded and re-raised unchanged, a success closes the
        route's circuit.
        """
        if self.circuit_breaker is None:
            return run()
        try:
            result = run()
        except Exception as exc:
            self.circuit_breaker.record_failure(route, exc)
            raise
        self.circuit_breaker.record_success(route)
        return result

    @staticmethod
    def _estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
        return sum(
            estimate_tokens(str(message.get("content") or ""))
            for message in messages
            if isinstance(message, dict)
        )

    def _estimated_output_for(self, max_tokens: int | None = None) -> int:
        """Return the bounded output estimate used only for admission.

        ``max_tokens`` is a provider-side generation ceiling, not proof that the
        request will consume that many output tokens. Governance therefore uses
        the configured estimate as its normal reservation signal while honoring
        any explicitly smaller per-call ceiling.
        """
        if max_tokens is None:
            return self.estimated_output_tokens
        return min(max_tokens, self.estimated_output_tokens)

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string")
        if not isinstance(system_prompt, str):
            raise TypeError("system_prompt must be a string")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 0:
            raise ValueError("max_tokens must be a non-negative integer")
        route, llm = self._admit(
            ModelUsage(
                input_tokens=estimate_tokens(system_prompt) + estimate_tokens(prompt),
                output_tokens=self._estimated_output_for(max_tokens),
                llm_calls=1,
            )
        )
        result = self._execute(
            llm,
            route,
            lambda: llm.generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        )
        return result

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        if not isinstance(messages, list) or not messages:
            raise TypeError("messages must be a non-empty list")
        input_tokens = self._estimate_message_tokens(messages)
        if tools:
            input_tokens += estimate_tokens(str(tools))
        route, llm = self._admit(
            ModelUsage(
                input_tokens=input_tokens,
                output_tokens=self._estimated_output_for(),
                llm_calls=1,
            )
        )
        result = self._execute(
            llm,
            route,
            lambda: llm.generate_with_tools(messages, tools=tools, tool_choice=tool_choice),
        )
        return result

    def __getattr__(self, name: str) -> Any:
        """Preserve compatibility for provider-specific read-only attributes."""
        if name in {"project_id", "governance", "usage_ledger", "routes", "metrics"}:
            raise AttributeError(name)
        routes = object.__getattribute__(self, "routes")
        for llm in routes.values():
            try:
                return getattr(llm, name)
            except AttributeError:
                continue
        raise AttributeError(name)
