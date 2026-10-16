"""Cost report: per-route breakdown, unrated honesty, CLI and delivery wiring."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from runtime.cost_report import build_cost_report, write_cost_report
from runtime.model_cost import ModelCostRate, ModelCostRateRegistry
from runtime.model_governance import ModelRoute, ModelUsage
from runtime.model_usage import ModelUsageLedger


def _ledger_with_rates() -> tuple[ModelUsageLedger, ModelCostRateRegistry, ModelRoute]:
    ledger = ModelUsageLedger()
    rated = ModelRoute(provider="deepseek", model="deepseek-chat")
    unrated = ModelRoute(provider="agnes", model="agnes-2.5-flash")
    ledger.record("p1", ModelUsage(input_tokens=10_000, output_tokens=2_000, llm_calls=5), route=rated)
    ledger.record("p1", ModelUsage(input_tokens=1_000, output_tokens=500, llm_calls=2), route=unrated)
    registry = ModelCostRateRegistry({
        rated: ModelCostRate(input_usd_per_million_tokens="0.27", output_usd_per_million_tokens="1.10"),
    })
    return ledger, registry, rated


def test_report_breaks_down_per_route_with_exact_totals():
    ledger, registry, _ = _ledger_with_rates()

    report = build_cost_report(ledger, registry, project_id="p1")

    assert report.total_input_tokens == 11_000
    assert report.total_output_tokens == 2_500
    assert report.total_llm_calls() == 7
    assert report.total_cost_usd == Decimal("0.0049")


def test_unrated_route_is_reported_not_dropped():
    ledger, registry, _ = _ledger_with_rates()

    report = build_cost_report(ledger, registry, project_id="p1")

    assert report.unrated_routes == ("agnes/agnes-2.5-flash",)
    markdown = report.render_markdown(project="demo")
    assert "未配置成本费率" in markdown
    assert "agnes/agnes-2.5-flash" in markdown
    # The unrated usage is still visible as a row.
    assert "| agnes/agnes-2.5-flash | 2 | 1,000 | 500 | $0.0000 |" in markdown


def test_empty_ledger_renders_placeholder():
    report = build_cost_report(ModelUsageLedger(), ModelCostRateRegistry(), project_id="empty")

    assert report.total_llm_calls() == 0
    assert "无已记录的模型用量" in report.render_markdown()


def test_write_cost_report_creates_doc(tmp_path: Path):
    ledger, registry, _ = _ledger_with_rates()
    report = build_cost_report(ledger, registry, project_id="p1")

    path = write_cost_report(tmp_path, report, project="wordcount")

    assert path.name == "cost_report.md"
    assert "wordcount" in path.read_text(encoding="utf-8")


def test_ledger_without_route_records_is_tolerated():
    ledger = ModelUsageLedger()
    # records exist but all lack route attribution
    ledger.record("p2", ModelUsage(input_tokens=1, output_tokens=1, llm_calls=1), route=None)

    report = build_cost_report(ledger, ModelCostRateRegistry(), project_id="p2")

    assert report.total_llm_calls() == 0
    assert report.per_route == ()


def test_cost_rates_env_config_roundtrip(monkeypatch):
    monkeypatch.setenv("AI_TEAM_COST_RATES_JSON", json.dumps({
        "deepseek/deepseek-chat": {"input": 0.27, "output": 1.10},
    }))
    import main
    registry = main._load_cost_rate_registry()
    route = ModelRoute(provider="deepseek", model="deepseek-chat")
    cost = registry.estimate(route, ModelUsage(input_tokens=1_000_000, output_tokens=0, llm_calls=0))
    assert cost == Decimal("0.27")


def test_invalid_cost_rates_env_is_rejected(monkeypatch):
    monkeypatch.setenv("AI_TEAM_COST_RATES_JSON", "{not json")
    import main
    with pytest.raises(ValueError, match="invalid AI_TEAM_COST_RATES_JSON"):
        main._load_cost_rate_registry()


def test_json_result_includes_cost_section():
    import main
    from runtime.task import Task
    from runtime.task_manager import TaskManager

    class FakeResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1

        def to_dict(self):
            return {"success": True}

    manager = TaskManager([Task(id="T1", title="t", description="d", role="developer", status="completed")])
    ledger, registry, _ = _ledger_with_rates()
    report = build_cost_report(ledger, registry, project_id="p1")

    payload = json.loads(main._json_result(manager, FakeResult(), cost_summary=report.to_dict()))
    assert payload["cost"]["total_cost_usd"] == "0.0049"
    assert payload["cost"]["unrated_routes"] == ["agnes/agnes-2.5-flash"]

    plain = json.loads(main._json_result(manager, FakeResult()))
    assert "cost" not in plain
