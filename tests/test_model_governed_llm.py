from types import SimpleNamespace

import pytest

from runtime.llm.base import BaseLLM, LLMResponse
from runtime.model_governance import (
    ModelGovernance,
    ModelGovernancePolicy,
    ModelRoute,
    ModelUsage,
    ProjectModelBudget,
)
from runtime.model_governed_llm import ModelAdmissionError, ModelGovernedLLM
from runtime.model_usage import ModelUsageLedger


class _LLM(BaseLLM):
    def __init__(self, name: str):
        self.name = name
        self.generate_calls = 0
        self.tool_calls = 0

    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        self.generate_calls += 1
        return f"{self.name}:ok"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto") -> LLMResponse:
        self.tool_calls += 1
        return LLMResponse(content=f"{self.name}:ok")


def _setup(*, budget: ProjectModelBudget | None = None, fallback: bool = True):
    primary = ModelRoute("agnes", "primary")
    backup = ModelRoute("backup", "fallback")
    policy = ModelGovernancePolicy(
        project_id="P1",
        primary=primary,
        fallback=backup if fallback else None,
        budget=budget or ProjectModelBudget(1000, 1000, 2),
    )
    governance = ModelGovernance([policy])
    ledger = ModelUsageLedger()
    primary_llm = _LLM("primary")
    backup_llm = _LLM("fallback")
    governed = ModelGovernedLLM(
        project_id="P1",
        governance=governance,
        usage_ledger=ledger,
        routes={primary: primary_llm, backup: backup_llm},
        estimated_output_tokens=100,
    )
    return governed, ledger, primary_llm, backup_llm


def test_admitted_generate_uses_primary_route_without_mutating_ledger():
    governed, ledger, primary, backup = _setup()

    assert governed.generate("hello", system_prompt="system", max_tokens=50) == "primary:ok"
    assert primary.generate_calls == 1
    assert backup.generate_calls == 0
    assert ledger.usage_for("P1") == ModelUsage()


def test_call_budget_is_enforced_before_provider_invocation():
    governed, ledger, primary, _ = _setup(budget=ProjectModelBudget(1000, 1000, 1))
    ledger.record("P1", ModelUsage(llm_calls=1), route=ModelRoute("agnes", "primary"))

    with pytest.raises(ModelAdmissionError, match="project LLM-call budget exceeded"):
        governed.generate("hello")
    assert primary.generate_calls == 0


def test_unhealthy_primary_selects_configured_fallback():
    governed, _, primary, backup = _setup()
    governed.primary_healthy = False

    assert governed.generate("hello") == "fallback:ok"
    assert primary.generate_calls == 0
    assert backup.generate_calls == 1


def test_missing_selected_route_fails_closed():
    governed, _, _, _ = _setup()
    governed.routes.pop(ModelRoute("agnes", "primary"))

    with pytest.raises(ModelAdmissionError, match="unconfigured route"):
        governed.generate("hello")


def test_health_callback_is_evaluated_at_each_invocation():
    health = {"value": True}
    governed, _, primary, backup = _setup()
    governed.primary_healthy = lambda: health["value"]

    governed.generate("first")
    health["value"] = False
    governed.generate("second")

    assert primary.generate_calls == 1
    assert backup.generate_calls == 1


def test_tool_call_path_is_governed():
    governed, _, primary, backup = _setup()

    result = governed.generate_with_tools(
        [{"role": "user", "content": "inspect"}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert result.content == "primary:ok"
    assert primary.tool_calls == 1
    assert backup.tool_calls == 0


def test_invalid_route_mapping_is_rejected():
    with pytest.raises(TypeError, match="route keys"):
        ModelGovernedLLM(
            project_id="P1",
            governance=_setup()[0].governance,
            usage_ledger=ModelUsageLedger(),
            routes={"not-a-route": _LLM("bad")},
        )
