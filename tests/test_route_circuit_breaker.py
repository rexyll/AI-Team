from __future__ import annotations

import pytest

from runtime.llm.base import BaseLLM, LLMResponse
from runtime.llm.circuit_breaker import (
    CircuitBreakerState,
    RouteCircuitBreaker,
    RouteCircuitBreakerConfig,
)
from runtime.model_governance import (
    ModelGovernance,
    ModelGovernancePolicy,
    ModelRoute,
    ProjectModelBudget,
)
from runtime.model_governed_llm import ModelGovernedLLM
from runtime.model_usage import ModelUsageLedger


class _FlakyLLM(BaseLLM):
    def __init__(self, name: str, failures_before_success: int = 0):
        self.name = name
        self.calls = 0
        self.failures_before_success = failures_before_success

    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError(f"{self.name} provider down")
        return f"{self.name}:ok"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto") -> LLMResponse:
        raise AssertionError("not used in this suite")


def _breaker(*, threshold: int = 3, cooldown: float = 30.0, clock=None) -> RouteCircuitBreaker:
    return RouteCircuitBreaker(
        config=RouteCircuitBreakerConfig(failure_threshold=threshold, recovery_timeout_s=cooldown),
        clock=clock,
    )


def test_stays_closed_under_threshold_and_opens_at_threshold():
    route = ModelRoute("agnes", "primary")
    breaker = _breaker(threshold=3)

    breaker.record_failure(route)
    breaker.record_failure(route)
    assert breaker.is_healthy(route) is True
    assert breaker.state_of(route) is CircuitBreakerState.CLOSED

    breaker.record_failure(route)
    assert breaker.state_of(route) is CircuitBreakerState.OPEN
    assert breaker.is_healthy(route) is False


def test_open_circuit_admits_probe_after_cooldown_and_recovers_on_success():
    route = ModelRoute("agnes", "primary")
    now = [100.0]
    breaker = _breaker(threshold=1, cooldown=30.0, clock=lambda: now[0])

    breaker.record_failure(route, RuntimeError("provider down"))
    assert breaker.is_healthy(route) is False

    now[0] += 31.0
    assert breaker.is_healthy(route) is True  # half-open probe admitted
    breaker.record_success(route)
    assert breaker.state_of(route) is CircuitBreakerState.CLOSED
    assert breaker.is_healthy(route) is True

    snapshot = breaker.snapshot(route)
    entry = snapshot["agnes/primary"]
    assert entry["state"] == "closed"
    assert [event["event"] for event in entry["recent_events"]] == ["open", "half_open", "closed"]


def test_failed_probe_reopens_immediately():
    route = ModelRoute("agnes", "primary")
    now = [0.0]
    breaker = _breaker(threshold=1, cooldown=10.0, clock=lambda: now[0])

    breaker.record_failure(route)
    now[0] += 11.0
    assert breaker.is_healthy(route) is True  # probe
    breaker.record_failure(route)
    assert breaker.state_of(route) is CircuitBreakerState.OPEN
    assert breaker.is_healthy(route) is False


def test_success_resets_consecutive_failure_count():
    route = ModelRoute("agnes", "primary")
    breaker = _breaker(threshold=2)

    breaker.record_failure(route)
    breaker.record_success(route)
    breaker.record_failure(route)

    assert breaker.state_of(route) is CircuitBreakerState.CLOSED


def test_isolated_routes_do_not_affect_each_other():
    primary = ModelRoute("agnes", "primary")
    other = ModelRoute("backup", "fallback")
    breaker = _breaker(threshold=1)

    breaker.record_failure(primary)

    assert breaker.state_of(primary) is CircuitBreakerState.OPEN
    assert breaker.is_healthy(other) is True


def test_governed_llm_opens_circuit_and_falls_back_to_healthy_route():
    primary = ModelRoute("agnes", "primary")
    backup = ModelRoute("backup", "fallback")
    policy = ModelGovernancePolicy(
        project_id="P1",
        primary=primary,
        fallback=backup,
        budget=ProjectModelBudget(100_000, 100_000, 100),
    )
    breaker = _breaker(threshold=2, cooldown=3600.0)
    governed = ModelGovernedLLM(
        project_id="P1",
        governance=ModelGovernance([policy]),
        usage_ledger=ModelUsageLedger(),
        routes={primary: _FlakyLLM("primary", failures_before_success=10), backup: _FlakyLLM("fallback")},
        estimated_output_tokens=10,
        circuit_breaker=breaker,
        primary_route=primary,
    )

    # Two consecutive provider failures are recorded and re-raised unchanged;
    # reaching the threshold opens the circuit.
    with pytest.raises(RuntimeError):
        governed.generate("one")
    with pytest.raises(RuntimeError):
        governed.generate("two")
    assert breaker.state_of(primary) is CircuitBreakerState.OPEN

    # Admission now falls back to the healthy route instead of touching the
    # broken primary again.
    assert governed.generate("three") == "fallback:ok"
    assert breaker.state_of(primary) is CircuitBreakerState.OPEN
    assert breaker.snapshot(primary)["agnes/primary"]["total_rejections"] == 1


def test_governed_llm_requires_primary_route_with_breaker():
    primary = ModelRoute("agnes", "primary")
    policy = ModelGovernancePolicy(
        project_id="P1",
        primary=primary,
        fallback=None,
        budget=ProjectModelBudget(1000, 1000, 10),
    )
    with pytest.raises(ValueError):
        ModelGovernedLLM(
            project_id="P1",
            governance=ModelGovernance([policy]),
            usage_ledger=ModelUsageLedger(),
            routes={primary: _FlakyLLM("primary")},
            circuit_breaker=_breaker(),
        )
