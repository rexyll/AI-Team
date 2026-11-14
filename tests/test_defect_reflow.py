"""Defect intake and hotfix reflow contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents.doc_writer import DocWriterAgent
from core.hotfix_runner import run_hotfix
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter
from runtime.defect_reflow import (
    Defect,
    build_hotfix_change_request,
    build_hotfix_plan,
    load_defect_intake,
    parse_defect_intake,
    prepare_hotfix,
    write_hotfix_artifacts,
)
from runtime.llm.base import BaseLLM
from runtime.task import Task
from runtime.task_validator import validate_plan
from security.workspace import WorkspaceSandbox

_NOW = datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc)

INTAKE = """# 缺陷清单

## 缺陷 DEF-001 登录后立即退出
- 严重级别: 严重
- 影响版本: v0.1.0
- 描述: 输入正确凭据后进程退出。
- 复现步骤: 运行 login 命令，输入 admin/admin。

## 缺陷 DEF-002 导出结果缺少表头
- 严重级别: minor
- 描述: 导出 CSV 时第一行不是表头。
"""

REQUIREMENTS_DOC = """# 需求规格说明

### REQ-001 登录（必须）
验收标准：登录成功后可继续操作。
"""


def _seed_release(root: Path, *, version: str = "0.1.0") -> None:
    root.mkdir(parents=True, exist_ok=True)
    log = {
        "releases": [{
            "version": version,
            "tag": f"v{version}",
            "commit": "a" * 40,
            "project": "todo",
            "created_at": "2026-11-03T00:00:00Z",
            "acceptance_verdict": "passed",
            "integration_status": "passed",
            "integration_rounds": 0,
            "deliverable_dir": ".",
        }]
    }
    (root / "release_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "requirements.md").write_text(REQUIREMENTS_DOC, encoding="utf-8")
    (root / "docs" / "acceptance_tests.json").write_text(
        json.dumps({
            "schema_version": 1,
            "tests": [{
                "test_id": "AT-001",
                "requirement_id": "REQ-001",
                "selector": "test_todo::test_ok",
            }],
        }),
        encoding="utf-8",
    )


def test_parse_defect_intake_normalizes_severity_and_versions():
    defects = parse_defect_intake(INTAKE)

    assert [defect.defect_id for defect in defects] == ["DEF-001", "DEF-002"]
    assert defects[0].severity == "major"
    assert defects[0].severity_label == "严重"
    assert defects[0].affected_version == "0.1.0"
    assert defects[0].reproduction
    assert defects[1].severity == "minor"
    assert defects[1].affected_version is None


@pytest.mark.parametrize(
    "document, message",
    [
        ("## 缺陷 DEF-001 标题\n- 描述: 有描述\n", "缺少字段"),
        ("## 缺陷 DEF-001 标题\n- 严重级别: 严重\n", "缺少字段"),
        ("## 缺陷 DEF-001 标题\n- 严重级别: 未知\n- 描述: x\n", "严重级别非法"),
        ("## 缺陷 DEF-001 标题\n- 严重级别: 严重\n- 描述: x\n- 优先级: 高\n", "未知字段"),
        ("## 缺陷 DEF-001 标题\n- 严重级别: 严重\n- 描述: x\n\n## 缺陷 DEF-001 重复\n- 严重级别: 一般\n- 描述: y\n", "重复"),
        ("## 缺陷 DEF-001\n- 严重级别: 严重\n- 描述: x\n", "格式非法"),
        ("# 缺陷清单\n\n无缺陷\n", "清单为空"),
    ],
)
def test_parse_defect_intake_rejects_invalid_documents(document: str, message: str):
    with pytest.raises(ValueError, match=message):
        parse_defect_intake(document)


def test_load_defect_intake_rejects_empty_file(tmp_path: Path):
    empty = tmp_path / "defects.md"
    empty.write_text("  \n", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be empty"):
        load_defect_intake(empty)


def test_prepare_hotfix_builds_valid_plan_and_change_request(tmp_path: Path):
    root = tmp_path / "delivered"
    _seed_release(root)

    preparation = prepare_hotfix(root, INTAKE)

    assert preparation.baseline_version == "0.1.0"
    assert preparation.hotfix_version == "0.1.1"
    assert preparation.project == "todo"
    validate_plan(preparation.plan)
    task_ids = [task["id"] for task in preparation.plan["tasks"]]
    assert task_ids == [
        "DEF-001-FIX", "DEF-001-VERIFY",
        "DEF-002-FIX", "DEF-002-VERIFY",
        "HOTFIX-REVIEW",
    ]
    review = preparation.plan["tasks"][-1]
    assert review["dependencies"] == ["DEF-001-VERIFY", "DEF-002-VERIFY"]
    assert "<untrusted-data" in preparation.plan["tasks"][0]["description"]
    assert "变更 1（CHG-001）：修复 DEF-001" in preparation.change_request
    assert "目标版本：v0.1.1" in preparation.change_request


def test_prepare_hotfix_requires_release_history(tmp_path: Path):
    root = tmp_path / "delivered"
    root.mkdir()
    with pytest.raises(ValueError, match="热修需要已发布的交付物"):
        prepare_hotfix(root, INTAKE)


def test_prepare_hotfix_rejects_unknown_affected_version(tmp_path: Path):
    root = tmp_path / "delivered"
    _seed_release(root)
    intake = INTAKE.replace("- 影响版本: v0.1.0", "- 影响版本: v0.9.9")

    with pytest.raises(ValueError, match="不在发布历史中"):
        prepare_hotfix(root, intake)


def test_prepare_hotfix_rejects_already_released_version(tmp_path: Path):
    root = tmp_path / "delivered"
    _seed_release(root)

    with pytest.raises(ValueError, match="already been released"):
        prepare_hotfix(root, INTAKE, hotfix_version="0.1.0")


def test_prepare_hotfix_accepts_explicit_version(tmp_path: Path):
    root = tmp_path / "delivered"
    _seed_release(root)

    preparation = prepare_hotfix(root, INTAKE, hotfix_version="0.2.0")

    assert preparation.hotfix_version == "0.2.0"
    assert "v0.2.0" in preparation.change_request


def test_write_hotfix_artifacts_reports_fixed_outcome(tmp_path: Path):
    root = tmp_path / "delivered"
    _seed_release(root)
    preparation = prepare_hotfix(root, INTAKE)
    delivery = {
        "integration": {"status": "passed", "rounds": 1},
        "acceptance": {"verdict": "passed"},
        "qa": {"verdict": "QA_PASSED"},
        "release": {"status": "released", "version": "0.1.1", "tag": "v0.1.1"},
        "package": {"archive": "delivered-delivery.zip", "checksum": "b" * 64},
    }

    artifacts = write_hotfix_artifacts(
        preparation, status="fixed", delivery=delivery, now=_NOW
    )

    request_text = (root / "hotfix_request.md").read_text(encoding="utf-8")
    report_text = Path(artifacts["report"]).read_text(encoding="utf-8")
    assert "CHG-001" in request_text
    assert "FIXED（已修复并重新打包）" in report_text
    assert "| DEF-001 | 严重 | 登录后立即退出 | DEF-001-FIX | DEF-001-VERIFY | 已修复 |" in report_text
    assert "v0.1.1" in report_text
    assert "delivered-delivery.zip" in report_text
    assert artifacts["change_request"] == str(root / "hotfix_request.md")


def test_build_hotfix_plan_requires_defects():
    with pytest.raises(ValueError, match="at least one defect"):
        build_hotfix_plan(
            project="todo", defects=[], baseline_version="0.1.0", hotfix_version="0.1.1"
        )


def test_build_hotfix_change_request_maps_each_defect():
    text = build_hotfix_change_request(
        defects=[Defect("DEF-001", "登录退出", "major", "进程退出")],
        baseline_version="0.1.0",
        hotfix_version="0.1.1",
    )

    assert "变更 1（CHG-001）：修复 DEF-001 登录退出" in text
    assert "验收标准：该缺陷不可复现" in text


class _FixedTextLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("not used")


class _DeveloperStub:
    role = "developer"

    def __init__(self, deliverable: Path):
        self._deliverable = deliverable
        self.calls: list[Task] = []

    def run(self, task: Task) -> dict:
        self.calls.append(task)
        self._deliverable.mkdir(parents=True, exist_ok=True)
        (self._deliverable / "todo.py").write_text("MESSAGE = 'ok'\n", encoding="utf-8")
        (self._deliverable / "test_todo.py").write_text(
            "import todo\n\ndef test_ok():\n    assert todo.MESSAGE == 'ok'\n",
            encoding="utf-8",
        )
        return {"status": "completed", "agent": "developer", "task_id": task.id,
                "message": "hotfix implemented"}


class _DictStubAgent:
    def __init__(self, role: str, status: str, message: str):
        self._role = role
        self._status = status
        self._message = message
        self.calls: list[Task] = []

    @property
    def role(self) -> str:
        return self._role

    def run(self, task: Task) -> dict:
        self.calls.append(task)
        return {"status": self._status, "agent": self._role, "task_id": task.id,
                "message": self._message}


def _hotfix_router(parent: Path, deliverable: Path) -> AgentRouter:
    router = AgentRouter()
    router.register("developer", _DeveloperStub(deliverable))
    router.register("tester", _DictStubAgent("tester", "passed", "TEST_PASSED"))
    router.register("reviewer", _DictStubAgent("reviewer", "approved", "APPROVED"))
    router.register(
        "doc_writer",
        DocWriterAgent(
            AgentConfig(role="doc_writer", model=""),
            llm=_FixedTextLLM("# 交付文档\n\nREQ-001 已实现，测试通过。\n"),
            sandbox=WorkspaceSandbox(parent),
        ),
    )
    return router


def test_run_hotfix_repackages_and_records_new_version(tmp_path: Path):
    root = tmp_path / "delivered"
    _seed_release(root)
    router = _hotfix_router(tmp_path, root)

    outcome = run_hotfix(router, root, INTAKE, auto_release=True, now=_NOW)

    assert outcome["status"] == "fixed"
    assert outcome["baseline_version"] == "0.1.0"
    assert outcome["version"] == "0.1.1"
    delivery = outcome["delivery"]
    assert delivery["integration"]["status"] == "passed"
    assert delivery["package"] is not None
    assert delivery["release"]["tag"] == "v0.1.1"
    report = Path(outcome["report"]).read_text(encoding="utf-8")
    assert "FIXED（已修复并重新打包）" in report
    assert "DEF-002-VERIFY" in report
    assert (root / "hotfix_request.md").is_file()
    assert (root / "docs" / "defect_report.md").is_file()
    task_ids = [task.id for task in outcome["task_manager"].get_all_tasks()]
    assert task_ids == [
        "DEF-001-FIX", "DEF-001-VERIFY",
        "DEF-002-FIX", "DEF-002-VERIFY",
        "HOTFIX-REVIEW",
    ]


def test_run_hotfix_reports_pending_when_release_not_confirmed(tmp_path: Path):
    root = tmp_path / "delivered"
    _seed_release(root)
    router = _hotfix_router(tmp_path, root)

    outcome = run_hotfix(router, root, INTAKE, auto_release=False, now=_NOW)

    assert outcome["status"] == "pending"
    assert "发布待确认" in outcome["reason"]
    report = Path(outcome["report"]).read_text(encoding="utf-8")
    assert "PENDING" in report
