from decimal import Decimal

import pytest

from runtime.model_cost import ModelCostError, ModelCostRate, ModelCostRateRegistry
from runtime.model_governance import ModelRoute, ModelUsage


def test_cost_rate_normalizes_decimal_values_and_estimates_usage() -> None:
    rate = ModelCostRate("2.00", 4, request_usd="0.01")
    usage = ModelUsage(input_tokens=500_000, output_tokens=250_000, llm_calls=2)

    assert rate.input_usd_per_million_tokens == Decimal("2.00")
    assert rate.output_usd_per_million_tokens == Decimal("4")
    assert rate.estimate(usage) == Decimal("2.02")


def test_registry_is_scoped_by_provider_and_model() -> None:
    primary = ModelRoute("Agnes", "agnes-2.5-flash")
    fallback = ModelRoute("other", "model-x")
    registry = ModelCostRateRegistry({primary: ModelCostRate(1, 2), fallback: ModelCostRate(3, 4)})

    assert registry.rate_for(primary).input_usd_per_million_tokens == Decimal("1")
    assert registry.estimate(primary, ModelUsage(input_tokens=1_000_000, output_tokens=500_000)) == Decimal("2")
    assert registry.routes() == (primary, fallback)


def test_missing_route_has_explicit_error() -> None:
    route = ModelRoute("agnes", "unknown")
    with pytest.raises(KeyError, match="No cost rate configured"):
        ModelCostRateRegistry().rate_for(route)


def test_cost_rates_reject_negative_or_invalid_values() -> None:
    with pytest.raises(ModelCostError):
        ModelCostRate(-1, 1)
    with pytest.raises(ModelCostError):
        ModelCostRate("not-a-number", 1)


def test_estimate_requires_model_usage() -> None:
    rate = ModelCostRate(1, 1)
    with pytest.raises(TypeError, match="usage must be a ModelUsage"):
        rate.estimate(object())
