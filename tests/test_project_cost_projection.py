from decimal import Decimal

import pytest

from runtime.model_cost import ModelCostError, ModelCostRate, ModelCostRateRegistry, ProjectCostProjection
from runtime.model_governance import ModelRoute, ModelUsage
from runtime.model_usage import ModelUsageLedger


def test_project_cost_projection_aggregates_multiple_routes() -> None:
    primary = ModelRoute("agnes", "agnes-2.5-flash")
    fallback = ModelRoute("other", "model-x")
    ledger = ModelUsageLedger()
    ledger.record("P1", ModelUsage(input_tokens=500_000, output_tokens=250_000, llm_calls=1), route=primary)
    ledger.record("P1", ModelUsage(input_tokens=1_000_000, output_tokens=500_000, llm_calls=2), route=fallback)
    ledger.record("P2", ModelUsage(input_tokens=1_000_000, output_tokens=1_000_000, llm_calls=1), route=primary)
    registry = ModelCostRateRegistry(
        {
            primary: ModelCostRate("2", "4", request_usd="0.01"),
            fallback: ModelCostRate("1", "3", request_usd="0.02"),
        }
    )

    estimate = ProjectCostProjection(registry).estimate_project(ledger, "P1")

    assert estimate.usage == ModelUsage(input_tokens=1_500_000, output_tokens=750_000, llm_calls=3)
    assert estimate.cost_usd == Decimal("5.51")
    assert estimate.routes == (primary, fallback)


def test_project_cost_projection_isolated_by_project() -> None:
    route = ModelRoute("agnes", "model")
    ledger = ModelUsageLedger()
    ledger.record("P1", ModelUsage(input_tokens=1_000_000), route=route)
    ledger.record("P2", ModelUsage(input_tokens=2_000_000), route=route)
    registry = ModelCostRateRegistry({route: ModelCostRate(2, 4)})

    estimate = ProjectCostProjection(registry).estimate_project(ledger, "P1")

    assert estimate.usage == ModelUsage(input_tokens=1_000_000)
    assert estimate.cost_usd == Decimal("2")


def test_project_cost_projection_rejects_legacy_unattributed_record() -> None:
    ledger = ModelUsageLedger()
    ledger.record("P1", ModelUsage(input_tokens=100))
    registry = ModelCostRateRegistry({ModelRoute("agnes", "model"): ModelCostRate(1, 1)})

    with pytest.raises(ModelCostError, match="no model route"):
        ProjectCostProjection(registry).estimate_project(ledger, "P1")


def test_project_cost_projection_empty_project_is_zero() -> None:
    registry = ModelCostRateRegistry()

    estimate = ProjectCostProjection(registry).estimate_project(ModelUsageLedger(), "missing")

    assert estimate.usage == ModelUsage()
    assert estimate.cost_usd == Decimal("0")
    assert estimate.routes == ()
