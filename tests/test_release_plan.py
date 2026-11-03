"""Milestone release-planning contracts: parsing, batch outcomes, history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import main
from runtime.host_git import HostGitOperationService
from runtime.release import RELEASE_LOG_FILENAME, build_release_notes, load_release_log, perform_release, ReleaseRequest
from runtime.release_plan import (
    collect_release_history,
    load_release_plan_file,
    parse_release_plan,
    render_release_history,
    write_release_plan,
)
from security.workspace import WorkspaceSandbox

_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)

PLAN_TEXT = """# 发布计划：记账工具分期交付

## 里程碑 M1：基础可用
### 需求 R1：记账核心 [v0.1.0]
开发一个命令行记账工具，支持添加与列表。

### 需求 R2：账单统计
增加月度汇总输出，所有文件放在 workspace/ledger 目录下。

## 里程碑 M2：增强
### 需求 R3：导出
支持导出 CSV。
"""


def test_parse_release_plan_keeps_milestones_and_requirements_in_order():
    plan = parse_release_plan(PLAN_TEXT)

    assert plan.title == "发布计划：记账工具分期交付"
    assert plan.milestones == ("M1：基础可用", "M2：增强")
    assert [entry.title for entry in plan.entries] == ["记账核心", "账单统计", "导出"]
    assert [entry.version for entry in plan.entries] == ["0.1.0", None, None]
    assert plan.entries[0].milestone == "M1：基础可用"
    assert "支持添加与列表" in plan.entries[0].requirement
    assert len(plan.entries_for("M2：增强")) == 1


def test_parse_release_plan_defaults_title_and_strips_bom():
    plan = parse_release_plan("\ufeff## 里程碑 M1\n### 需求：A\n需求正文\n")

    assert plan.title == "发布计划"
    assert plan.entries[0].title == "A"


@pytest.mark.parametrize(
    "document",
    [
        "",
        "   \n",
        "### 需求 A\n正文\n",
        "## 里程碑 M1\n### 需求 A\n\n",
        "## 里程碑 M1\n## 里程碑 M1\n### 需求 A\n正文\n",
        "## 里程碑 M1\n### 需求 A [v1.2]\n正文\n",
    ],
)
def test_parse_release_plan_fails_closed(document: str):
    with pytest.raises(ValueError):
        parse_release_plan(document)


def test_load_release_plan_file_rejects_empty(tmp_path: Path):
    path = tmp_path / "plan.md"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        load_release_plan_file(path)


def test_render_release_plan_records_outcomes(tmp_path: Path):
    plan = parse_release_plan(PLAN_TEXT)
    outcomes = [
        {
            "index": 1,
            "milestone": "M1：基础可用",
            "title": "记账核心",
            "status": "completed",
            "acceptance_verdict": "passed",
            "release": {
                "status": "released",
                "version": "0.1.0",
                "tag": "v0.1.0",
                "commit": "a" * 40,
            },
            "deliverable_root": str(tmp_path / "ledger"),
        },
        {
            "index": 2,
            "milestone": "M1：基础可用",
            "title": "账单统计",
            "status": "skipped",
            "acceptance_verdict": None,
            "release": None,
            "deliverable_root": None,
            "error": "previous requirement failed",
        },
        {
            "index": 3,
            "milestone": "M2：增强",
            "title": "导出",
            "status": "pending",
            "acceptance_verdict": None,
            "release": None,
            "deliverable_root": None,
        },
    ]

    output = write_release_plan(plan, outcomes, tmp_path / "out" / "release_plan.md", now=_NOW)

    text = output.read_text(encoding="utf-8")
    assert "## 里程碑 M1：基础可用" in text
    assert "### 1. 记账核心" in text
    assert "发布：released v0.1.0（tag v0.1.0" in text
    assert "交付状态：skipped" in text
    assert "错误：previous requirement failed" in text
    assert "执行结果：完成 1 / 总计 3" in text


def _write_release_log(root: Path, entries: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / RELEASE_LOG_FILENAME).write_text(
        json.dumps({"releases": entries}, ensure_ascii=False), encoding="utf-8"
    )


def test_collect_release_history_aggregates_and_sorts(tmp_path: Path):
    _write_release_log(tmp_path / "beta", [
        {"version": "0.10.0", "tag": "v0.10.0", "created_at": "2026-11-02T10:00:00Z"},
    ])
    _write_release_log(tmp_path / "alpha", [
        {"version": "0.2.0", "tag": "v0.2.0", "created_at": "2026-11-02T11:00:00Z", "milestone": "M1"},
        {"version": "0.9.0", "tag": "v0.9.0", "created_at": "2026-11-02T12:00:00Z"},
    ])
    _write_release_log(tmp_path / "alpha" / "nested" / "gamma", [
        {"version": "1.0.0", "tag": "v1.0.0", "created_at": "2026-11-03T08:00:00Z"},
    ])
    _write_release_log(tmp_path / ".hidden", [{"version": "0.0.1", "tag": "v0.0.1"}])

    records = collect_release_history(tmp_path)

    assert [record["deliverable"] for record in records] == [
        "beta",
        "alpha",
        "alpha",
        "alpha/nested/gamma",
    ]
    assert [record["version"] for record in records] == ["0.10.0", "0.2.0", "0.9.0", "1.0.0"]
    table = render_release_history(records)
    assert "| beta | 0.10.0 | v0.10.0 |" in table
    assert "| alpha | 0.2.0 | v0.2.0 |" in table
    assert "M1" in table


def test_collect_release_history_respects_depth_and_fails_closed(tmp_path: Path):
    _write_release_log(tmp_path / "alpha" / "nested" / "gamma", [{"version": "1.0.0"}])

    assert collect_release_history(tmp_path, max_depth=0) == []
    assert collect_release_history(tmp_path, max_depth=2) == []
    assert len(collect_release_history(tmp_path, max_depth=3)) == 1

    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / RELEASE_LOG_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        collect_release_history(tmp_path)


def test_collect_release_history_rejects_missing_root(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        collect_release_history(tmp_path / "missing")


def test_build_release_notes_and_log_carry_milestone(tmp_path: Path):
    notes = build_release_notes(
        project="ledger",
        version="0.1.0",
        created_at="2026-11-03T09:00:00Z",
        context={"deliverable_dir": ".", "milestone": "M1：基础可用"},
    )
    assert "- 里程碑：M1：基础可用" in notes

    deliverable = tmp_path / "ledger"
    deliverable.mkdir()
    (deliverable / "app.py").write_text("x = 1", encoding="utf-8")
    request = ReleaseRequest(
        deliverable_root=str(deliverable),
        project="ledger",
        auto_release=True,
    )
    perform_release(
        request,
        git_service=HostGitOperationService(sandbox=WorkspaceSandbox(tmp_path)),
        context={"deliverable_dir": ".", "milestone": "M1：基础可用", "now": _NOW},
    )

    log = load_release_log(deliverable)
    assert log[-1]["milestone"] == "M1：基础可用"


class _Result:
    def __init__(self, success: bool, acceptance_verdict: str | None = None) -> None:
        self.success = success
        self.status = "completed" if success else "failed"
        self.acceptance_verdict = acceptance_verdict


def test_run_release_plan_delivers_sequentially_and_stops_on_failure(tmp_path: Path):
    plan = parse_release_plan(PLAN_TEXT)
    calls: list[dict] = []

    def runner(requirement: str, **kwargs):
        calls.append({"requirement": requirement, **kwargs})
        if len(calls) == 2:
            raise RuntimeError("boom")
        kwargs["on_delivery"](
            {
                "deliverable_root": str(tmp_path / f"delivery-{len(calls)}"),
                "release": {"status": "released", "version": "0.1.0", "tag": "v0.1.0"},
            }
        )
        return object(), _Result(True, "passed")

    outcomes, path = main.run_release_plan(
        plan,
        plan_output=str(tmp_path / "release_plan.md"),
        runner=runner,
        now=_NOW,
    )

    assert len(calls) == 2
    assert calls[0]["milestone"] == "M1：基础可用"
    assert calls[0]["release_version"] == "0.1.0"
    assert calls[1]["release_version"] is None
    assert [outcome["status"] for outcome in outcomes] == ["completed", "failed", "skipped"]
    assert outcomes[0]["release"]["tag"] == "v0.1.0"
    text = path.read_text(encoding="utf-8")
    assert "执行结果：完成 1 / 总计 3" in text
    assert "错误：RuntimeError: boom" in text
    assert "交付状态：skipped" in text


def test_run_release_plan_marks_unsuccessful_delivery_as_failed(tmp_path: Path):
    plan = parse_release_plan(PLAN_TEXT)

    def runner(requirement: str, **kwargs):
        return object(), _Result(False)

    outcomes, _ = main.run_release_plan(
        plan, plan_output=str(tmp_path / "release_plan.md"), runner=runner
    )

    assert [outcome["status"] for outcome in outcomes] == ["failed", "skipped", "skipped"]
    assert "did not succeed" in outcomes[0]["error"]


def test_cli_parser_exposes_plan_and_history_options(tmp_path: Path):
    parser = main.build_parser()

    args = parser.parse_args([
        "--requirements-file", str(tmp_path / "plan.md"),
        "--release-plan-output", str(tmp_path / "out.md"),
    ])
    assert args.requirements_file == str(tmp_path / "plan.md")
    assert args.release_plan_output == str(tmp_path / "out.md")
    assert parser.parse_args(["demo", "--milestone", "M1"]).milestone == "M1"
    assert parser.parse_args(["--release-history"]).release_history == ""
    assert parser.parse_args(["--release-history", "base"]).release_history == "base"


def test_main_runs_requirements_plan_and_writes_shared_plan(tmp_path: Path, monkeypatch, capsys):
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(PLAN_TEXT, encoding="utf-8")
    plan_output = tmp_path / "release_plan.md"
    captured: list[dict] = []

    def runner(requirement: str, **kwargs):
        captured.append(kwargs)
        kwargs["on_delivery"](
            {
                "deliverable_root": str(tmp_path / "ledger"),
                "release": {"status": "released", "version": kwargs["release_version"] or "0.1.1"},
            }
        )
        return object(), _Result(True, "passed")

    monkeypatch.setattr(main, "run_project", runner)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py",
        "--requirements-file", str(plan_file),
        "--release", "--auto-release",
        "--release-plan-output", str(plan_output),
        "--output", "json",
    ])

    exit_code = main.main()

    assert exit_code == 0
    assert len(captured) == 3
    assert captured[0]["release_version"] == "0.1.0"
    assert captured[0]["milestone"] == "M1：基础可用"
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan"] == str(plan_output)
    assert [outcome["status"] for outcome in payload["outcomes"]] == ["completed"] * 3
    assert payload["plan_meta"]["milestones"] == ["M1：基础可用", "M2：增强"]
    assert plan_output.is_file()


def test_main_requirements_plan_rejects_conflicting_options(tmp_path: Path, monkeypatch):
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(PLAN_TEXT, encoding="utf-8")
    monkeypatch.setattr(main.sys, "argv", [
        "main.py", "single requirement", "--requirements-file", str(plan_file),
    ])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


def test_main_release_history_prints_json(tmp_path: Path, monkeypatch, capsys):
    _write_release_log(tmp_path / "ledger", [
        {"version": "0.1.0", "tag": "v0.1.0", "created_at": "2026-11-03T09:00:00Z", "project": "ledger"},
    ])
    monkeypatch.setattr(main.sys, "argv", [
        "main.py", "--release-history", str(tmp_path), "--output", "json",
    ])

    assert main.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["root"] == str(tmp_path)
    assert payload["releases"][0]["version"] == "0.1.0"
    assert payload["releases"][0]["deliverable"] == "ledger"
