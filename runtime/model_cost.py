from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Mapping

from runtime.model_governance import ModelRoute, ModelUsage


class ModelCostError(ValueError):
    """Raised when model cost-rate configuration or estimation is invalid."""


@dataclass(frozen=True)
class ModelCostRate:
    """Immutable USD pricing for one provider/model route.

    Token prices are expressed per one million tokens. ``request_usd`` is an
    optional fixed charge applied once per LLM call.
    """

    input_usd_per_million_tokens: Decimal | int | float | str
    output_usd_per_million_tokens: Decimal | int | float | str
    request_usd: Decimal | int | float | str = Decimal("0")

    def __post_init__(self) -> None:
        for name in (
            "input_usd_per_million_tokens",
            "output_usd_per_million_tokens",
            "request_usd",
        ):
            try:
                value = Decimal(str(getattr(self, name)))
            except (InvalidOperation, ValueError) as exc:
                raise ModelCostError(f"{name} must be a valid decimal") from exc
            if not value.is_finite() or value < 0:
                raise ModelCostError(f"{name} must be a finite non-negative decimal")
            object.__setattr__(self, name, value)

    def estimate(self, usage: ModelUsage) -> Decimal:
        if not isinstance(usage, ModelUsage):
            raise TypeError("usage must be a ModelUsage")
        token_cost = (
            Decimal(usage.input_tokens) * self.input_usd_per_million_tokens
            + Decimal(usage.output_tokens) * self.output_usd_per_million_tokens
        ) / Decimal(1_000_000)
        return token_cost + Decimal(usage.llm_calls) * self.request_usd


class ModelCostRateRegistry:
    """Provider/model cost-rate lookup independent of admission decisions."""

    def __init__(self, rates: Mapping[ModelRoute, ModelCostRate] | None = None) -> None:
        if rates is None:
            rates = {}
        normalized: dict[ModelRoute, ModelCostRate] = {}
        for route, rate in rates.items():
            if not isinstance(route, ModelRoute):
                raise TypeError("all keys must be ModelRoute instances")
            if not isinstance(rate, ModelCostRate):
                raise TypeError("all values must be ModelCostRate instances")
            normalized[route] = rate
        self._rates = MappingProxyType(normalized)

    def rate_for(self, route: ModelRoute) -> ModelCostRate:
        if not isinstance(route, ModelRoute):
            raise TypeError("route must be a ModelRoute")
        try:
            return self._rates[route]
        except KeyError as exc:
            raise KeyError(f"No cost rate configured for {route.provider}/{route.model}") from exc

    def estimate(self, route: ModelRoute, usage: ModelUsage) -> Decimal:
        return self.rate_for(route).estimate(usage)

    def routes(self) -> tuple[ModelRoute, ...]:
        return tuple(self._rates)
