"""Project cost report: expose the usage ledger as a customer-visible artifact.

Reads the ModelUsageLedger through ProjectCostProjection (observational only)
and renders a per-route token/call/cost breakdown. Cost rates come from a
registry the caller supplies; routes without a configured rate are reported
honestly as "unpriced" instead of being dropped or estimated at zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from runtime.model_cost import ModelCostRateRegistry
from runtime.model_usage import ModelUsageLedger


@dataclass(frozen=True)
class CostReport:
    project_id: str
    total_cost_usd: Decimal
    total_input_tokens: int
    total_output_tokens: int
    per_route: tuple[dict[str, Any], ...]
    unrated_routes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "total_cost_usd": str(self.total_cost_usd),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_llm_calls": self.total_llm_calls(),
            "per_route": list(self.per_route),
            "unrated_routes": list(self.unrated_routes),
        }

    def total_llm_calls(self) -> int:
        return sum(int(route.get("llm_calls", 0)) for route in self.per_route)

    def render_markdown(self, *, project: str | None = None) -> str:
        title = project or self.project_id
        lines = [
            "# 模型成本报告（Cost Report）",
            "",
            f"- 项目：{title}",
            f"- 项目 ID：{self.project_id}",
            f"- LLM 调用次数：{self.total_llm_calls()}",
            f"- 输入 tokens：{self.total_input_tokens:,}",
            f"- 输出 tokens：{self.total_output_tokens:,}",
            f"- **总成本（USD）：${self.total_cost_usd:.4f}**",
            "",
        ]
        if self.per_route:
            lines.append("| 提供商/模型 | 调用 | 输入 tokens | 输出 tokens | 成本 (USD) |")
            lines.append("|---|---:|---:|---:|---:|")
            for route in self.per_route:
                lines.append(
                    f"| {route['provider']}/{route['model']} "
                    f"| {route['llm_calls']} "
                    f"| {route['input_tokens']:,} "
                    f"| {route['output_tokens']:,} "
                    f"| ${Decimal(route['cost_usd']):.4f} |"
                )
            lines.append("")
        if self.unrated_routes:
            lines.append(
                "以下路由未配置成本费率，其用量未计入总成本："
                + "、".join(self.unrated_routes)
            )
            lines.append("")
        if not self.per_route:
            lines.append("（无已记录的模型用量）")
        return "\n".join(lines) + "\n"


def build_cost_report(
    ledger: ModelUsageLedger,
    registry: Any,
    *,
    project_id: str,
) -> CostReport:
    """Build a CostReport; unrated routes are reported, never silently dropped.

    Total cost sums only the rated routes; the report says which routes were
    unpriced so the number is never silently incomplete.
    """
    if not isinstance(ledger, ModelUsageLedger):
        raise TypeError("ledger must be a ModelUsageLedger")
    if not isinstance(registry, ModelCostRateRegistry):
        raise TypeError("registry must be a ModelCostRateRegistry")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    project_id = project_id.strip()

    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for record in ledger.records(project_id):
        route = record.route
        if route is None:
            continue
        key = (route.provider, route.model)
        bucket = grouped.setdefault(
            key, {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        )
        bucket["llm_calls"] += record.usage.llm_calls
        bucket["input_tokens"] += record.usage.input_tokens
        bucket["output_tokens"] += record.usage.output_tokens

    total_cost = Decimal("0")
    total_input = total_output = total_calls = 0
    per_route: list[dict[str, Any]] = []
    unrated: list[str] = []
    for (provider, model), usage in grouped.items():
        total_input += usage["input_tokens"]
        total_output += usage["output_tokens"]
        total_calls += usage["llm_calls"]
        try:
            rate = registry.rate_for(_route_for(registry, provider, model))
            cost = rate.estimate(_usage_snapshot(usage))
        except KeyError:
            unrated.append(f"{provider}/{model}")
            cost = Decimal("0")
        total_cost += cost
        per_route.append({
            "provider": provider,
            "model": model,
            "llm_calls": usage["llm_calls"],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cost_usd": str(cost),
        })

    return CostReport(
        project_id=project_id,
        total_cost_usd=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        per_route=tuple(per_route),
        unrated_routes=tuple(unrated),
    )


def _route_for(registry: Any, provider: str, model: str):
    from runtime.model_governance import ModelRoute

    for route in registry.routes():
        if route.provider == provider and route.model == model:
            return route
    return ModelRoute(provider=provider, model=model)


def _usage_snapshot(usage: dict[str, int]):
    from runtime.model_governance import ModelUsage

    return ModelUsage(
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        llm_calls=usage["llm_calls"],
    )


def write_cost_report(root: Any, report: CostReport, *, project: str | None = None) -> Any:
    """Write docs/cost_report.md inside the deliverable root."""
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "cost_report.md"
    path.write_text(report.render_markdown(project=project), encoding="utf-8")
    return path
