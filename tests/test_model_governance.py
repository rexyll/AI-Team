import pytest

from runtime.model_governance import (
    ModelAdmissionDecision,
    ModelGovernance,
    ModelGovernanceError,
    ModelGovernancePolicy,
    ModelRoute,
    ModelUsage,
    ProjectModelBudget,
)


def _governance() -> ModelGovernance:
    return ModelGovernance(
        [
            ModelGovernancePolicy(
                project_id="P1",
                primary=ModelRoute("agnes", "agnes-2.5-flash"),
                fallback=ModelRoute("backup", "backup-fast"),
                budget=ProjectModelBudget(
                    max_input_tokens=1000,
                    max_output_tokens=500,
                    max_llm_calls=5,
                ),
            ),
            ModelGovernancePolicy(
                project_id="P2",
                primary=ModelRoute("agnes", "agnes-2.5-flash"),
                budget=ProjectModelBudget(
                    max_input_tokens=100,
                    max_output_tokens=100,
                    max_llm_calls=1,
                ),
            ),
        ]
    )


def test_admission_is_deterministic_and_does_not_mutate_usage():
    governance = _governance()
    usage = ModelUsage(input_tokens=100, output_tokens=20, llm_calls=1)
    request = ModelUsage(input_tokens=200, output_tokens=30, llm_calls=1)

    decision = governance.decide("P1", usage=usage, request=request)

    assert decision == ModelAdmissionDecision(
        admitted=True,
        route=ModelRoute("agnes", "agnes-2.5-flash"),
        reason=None,
    )
    assert usage == ModelUsage(input_tokens=100, output_tokens=20, llm_calls=1)


def test_project_budgets_are_isolated():
    governance = _governance()
    usage = ModelUsage(input_tokens=90, output_tokens=0, llm_calls=0)
    request = ModelUsage(input_tokens=20, output_tokens=0, llm_calls=1)

    decision = governance.decide("P2", usage=usage, request=request)

    assert decision.admitted is False
    assert decision.route is None
    assert decision.reason == "project input-token budget exceeded"

    p1 = governance.decide(
        "P1",
        usage=ModelUsage(),
        request=ModelUsage(input_tokens=20, output_tokens=10, llm_calls=1),
    )
    assert p1.admitted is True


def test_unhealthy_primary_uses_configured_fallback():
    decision = _governance().decide(
        "P1",
        usage=ModelUsage(),
        request=ModelUsage(input_tokens=10, output_tokens=10, llm_calls=1),
        primary_healthy=False,
    )

    assert decision.admitted is True
    assert decision.route == ModelRoute("backup", "backup-fast")
    assert decision.reason == "primary route unhealthy; fallback selected"


def test_unhealthy_primary_without_fallback_is_rejected():
    decision = _governance().decide(
        "P2",
        usage=ModelUsage(),
        request=ModelUsage(input_tokens=10, output_tokens=10, llm_calls=1),
        primary_healthy=False,
    )

    assert decision.admitted is False
    assert decision.route is None
    assert decision.reason == "primary route unhealthy and no fallback is configured"


def test_call_budget_is_enforced():
    decision = _governance().decide(
        "P1",
        usage=ModelUsage(llm_calls=5),
        request=ModelUsage(llm_calls=1),
    )

    assert decision.admitted is False
    assert decision.reason == "project LLM-call budget exceeded"


def test_unknown_project_is_rejected():
    with pytest.raises(KeyError, match="Unknown project"):
        _governance().policy_for("missing")


def test_duplicate_policy_is_rejected():
    policy = ModelGovernancePolicy(
        project_id="P1",
        primary=ModelRoute("agnes", "model"),
        budget=ProjectModelBudget(1, 1, 1),
    )
    with pytest.raises(ModelGovernanceError, match="duplicate project policy"):
        ModelGovernance([policy, policy])
