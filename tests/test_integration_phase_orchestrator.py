"""Orchestrator-level integration & regression phase contracts.

The product-level suite runs BEFORE documentation and packaging; a failed
suite feeds bounded developer-rework rounds through the canonical TaskWorkflow;
a suite that stays red after the last round is reported honestly and packaging
is skipped. The integration evidence rides into the DocWriter context so the
test report can carry it.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from agents.analyst import RequirementAnalystAgent
from agents.doc_writer import DocWriterAgent
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter
from runtime.llm.base import BaseLLM
from runtime.task import Task
from security.workspace import WorkspaceSandbox

ANALYSIS_MARKDOWN = """# 需求规格说明（草案）

## 一、项目概述
待办事项 CLI 工具。

## 二、功能需求清单
### REQ-001 待办管理（必须）
支持添加、列出、完成任务。
验收标准：CLI 命令实际可运行。

## 三、非功能需求
-【假设】单机运行。

## 四、验收标准
见 REQ-001。

## 五、假设与约束
-【假设】JSON 存储。

## 六、待确认问题
无。
"""

GOOD_TODO = "MESSAGE = 'ok'\n"
BROKEN_TODO = "MESSAGE = 'broken'\n"
TODO_TEST = "import todo\n\ndef test_ok():\n    assert todo.MESSAGE == 'ok'\n"


class _FixedTextLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("not used")


class _StubPlanner:
    role = "planner"

    def run(self, task: Task) -> dict:
        return {
            "plan": {
                "project": "todo",
                "summary": "待办事项 CLI 工具",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "实现 todo.py 与测试",
                        "description": "在 e2e_flat/ 下实现 todo.py 与 test_todo.py",
                        "role": "developer",
                        "dependencies": [],
                    }
                ],
            }
        }


class _DictStubAgent:
    """Dict-result stub following the orchestrator-workflow mock contract."""

    def __init__(self, role: str, status: str, message: str) -> None:
        self._role = role
        self._status = status
        self._message = message
        self.calls: list[Task] = []

    @property
    def role(self) -> str:
        return self._role

    def run(self, task: Task) -> dict:
        self.calls.append(task)
        return {
            "status": self._status,
            "agent": self._role,
            "task_id": task.id,
            "message": self._message,
        }


class _DeveloperStub:
    """Writes the deliverable product files and reacts to rework rounds."""

    role = "developer"

    def __init__(self, deliverable: Path, *, initial: str, rework_fixes: bool) -> None:
        self._deliverable = deliverable
        self._initial = initial
        self._rework_fixes = rework_fixes
        self.product_calls: list[Task] = []
        self.rework_calls: list[Task] = []

    def run(self, task: Task) -> dict:
        if task.id.startswith("REWORK-"):
            self.rework_calls.append(task)
            if self._rework_fixes:
                (self._deliverable / "todo.py").write_text(GOOD_TODO, encoding="utf-8")
            return {
                "status": "completed",
                "agent": "developer",
                "task_id": task.id,
                "message": "rework applied" if self._rework_fixes else "no-op rework",
            }
        self.product_calls.append(task)
        self._deliverable.mkdir(parents=True, exist_ok=True)
        (self._deliverable / "todo.py").write_text(self._initial, encoding="utf-8")
        (self._deliverable / "test_todo.py").write_text(TODO_TEST, encoding="utf-8")
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implemented",
        }


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _router(tmp_path: Path, developer: _DeveloperStub, doc_llm: _FixedTextLLM) -> AgentRouter:
    router = AgentRouter()
    router.register("analyst", RequirementAnalystAgent(
        AgentConfig(role="analyst", model=""), llm=_FixedTextLLM(ANALYSIS_MARKDOWN),
    ))
    router.register("planner", _StubPlanner())
    router.register("developer", developer)
    router.register("tester", _DictStubAgent("tester", "passed", "TEST_PASSED"))
    router.register("reviewer", _DictStubAgent("reviewer", "approved", "APPROVED"))
    router.register("doc_writer", DocWriterAgent(
        AgentConfig(role="doc_writer", model=""), llm=doc_llm, sandbox=WorkspaceSandbox(tmp_path),
    ))
    return router


def _run_project(tmp_path: Path, developer: _DeveloperStub) -> tuple[ProjectOrchestrator, dict]:
    doc_llm = _FixedTextLLM("# 测试结果报告\n\nREQ-001 已实现，集成回归证据见下。\n")
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path, developer, doc_llm),
        deliverable_dir="e2e_flat",
        sandbox=WorkspaceSandbox(tmp_path),
    )
    plan = orchestrator.create_plan("开发一个待办事项 CLI 工具")
    task_manager = orchestrator.build_task_manager(plan)
    orchestrator.execute(task_manager)
    assert orchestrator.last_delivery is not None
    return orchestrator, orchestrator.last_delivery


def test_integration_passes_first_round_and_evidence_reaches_docs(tmp_path: Path):
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=GOOD_TODO, rework_fixes=False)

    orchestrator, delivery = _run_project(tmp_path, developer)

    integration = delivery["integration"]
    assert integration["status"] == "passed"
    assert integration["rounds"] == 0
    assert integration["suite"]["summary"] == {"passed": 1}
    assert developer.rework_calls == []
    # Packaging proceeds and the doc writer received the integration evidence.
    assert delivery["package"] is not None
    doc_writer = orchestrator.agent_router.get_agent("doc_writer")
    assert any("集成回归验证（产品级）" in prompt for prompt in doc_writer.llm.prompts)
    # The deliverable ships with a monitoring contract, before the manifest.
    assert delivery["monitoring"]["status"] == "configured"
    assert delivery["monitoring"]["probes"] == [
        "release_anchor",
        "manifest_integrity",
        "smoke_suite",
    ]
    manifest_text = (tmp_path / "e2e_flat" / "DELIVERY_MANIFEST.md").read_text(encoding="utf-8")
    assert "monitoring/health_contract.json" in manifest_text
    assert "MONITORING.md" in manifest_text


def test_failed_suite_is_fixed_by_one_rework_round(tmp_path: Path):
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=BROKEN_TODO, rework_fixes=True)

    delivery = _run_project(tmp_path, developer)[1]

    integration = delivery["integration"]
    assert integration["status"] == "passed"
    assert integration["rounds"] == 1
    assert integration["rework_rounds"][0]["task_id"] == "REWORK-001"
    assert integration["rework_rounds"][0]["status"] == "completed"
    # The rework task carried fenced failure evidence.
    evidence = developer.rework_calls[0].context["integration_failure"]
    assert evidence["exit_code"] != 0
    assert "test_todo.py::test_ok" in evidence["failed_tests"]
    assert "<untrusted-data" in developer.rework_calls[0].description
    # Packaging proceeds after the suite turned green.
    assert delivery["package"] is not None


def test_suite_staying_red_skips_packaging_and_reports_honestly(tmp_path: Path):
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=BROKEN_TODO, rework_fixes=False)

    delivery = _run_project(tmp_path, developer)[1]

    integration = delivery["integration"]
    assert integration["status"] == "failed"
    assert integration["rounds"] == 2  # default AI_TEAM_INTEGRATION_MAX_ROUNDS
    assert integration["suite"]["summary"]["failed"] >= 1
    assert len(developer.rework_calls) == 2
    # Documents and manifest are still written (evidence of the failed state),
    # but a red suite is never packaged.
    assert delivery["package"] is None
    assert delivery["smoke"] is None
    assert (tmp_path / "e2e_flat" / "DELIVERY_MANIFEST.md").is_file()
    assert (tmp_path / "e2e_flat" / "docs" / "test_report.md").is_file()


def test_rework_rounds_can_be_disabled_by_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_TEAM_INTEGRATION_MAX_ROUNDS", "0")
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=BROKEN_TODO, rework_fixes=False)

    delivery = _run_project(tmp_path, developer)[1]

    integration = delivery["integration"]
    assert integration["status"] == "failed"
    assert integration["rounds"] == 0
    assert integration["rework_rounds"] == []
    assert delivery["package"] is None


def test_suite_skips_when_deliverable_has_no_tests(tmp_path: Path):
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=GOOD_TODO, rework_fixes=False)
    # Override the product output: code only, no test files.
    original_run = developer.run

    def run_without_tests(task: Task) -> dict:
        result = original_run(task)
        if not task.id.startswith("REWORK-"):
            (tmp_path / "e2e_flat" / "test_todo.py").unlink(missing_ok=True)
        return result

    developer.run = run_without_tests  # type: ignore[method-assign]

    delivery = _run_project(tmp_path, developer)[1]

    integration = delivery["integration"]
    assert integration["status"] == "skipped"
    assert integration["suite"]["reason"] == "no test files found"
    # Packaging proceeds; the absence of evidence is recorded, not hidden.
    assert delivery["package"] is not None


def test_release_phase_anchors_delivered_product_and_package_carries_notes(tmp_path: Path):
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=GOOD_TODO, rework_fixes=False)
    doc_llm = _FixedTextLLM("# 测试结果报告\n\nREQ-001 已实现，集成回归证据见下。\n")
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path, developer, doc_llm),
        deliverable_dir="e2e_flat",
        sandbox=WorkspaceSandbox(tmp_path),
        release_requested=True,
        auto_release=True,
    )
    plan = orchestrator.create_plan("开发一个待办事项 CLI 工具")
    task_manager = orchestrator.build_task_manager(plan)
    orchestrator.execute(task_manager)

    delivery = orchestrator.last_delivery
    release = delivery["release"]
    assert release["status"] == "released"
    assert release["tag"] == "v0.1.0"
    assert len(release["commit"]) == 40
    assert release["package"]["checksum"]
    # The checksummed manifest lists the release artifacts; the package carries them.
    manifest_text = (tmp_path / "e2e_flat" / "DELIVERY_MANIFEST.md").read_text(encoding="utf-8")
    assert "RELEASE_NOTES.md" in manifest_text
    assert "release_log.json" in manifest_text
    assert "monitoring/health_contract.json" in manifest_text
    with zipfile.ZipFile(delivery["package"]["archive"]) as bundle_zip:
        members = set(bundle_zip.namelist())
    assert {"RELEASE_NOTES.md", "release_log.json", "MONITORING.md"} <= members


def test_release_phase_skipped_without_release_request(tmp_path: Path):
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=GOOD_TODO, rework_fixes=False)

    delivery = _run_project(tmp_path, developer)[1]

    assert delivery["release"] is None


def test_release_phase_skipped_when_integration_failed(tmp_path: Path):
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=BROKEN_TODO, rework_fixes=False)
    doc_llm = _FixedTextLLM("# 测试结果报告\n\n回归失败。\n")
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path, developer, doc_llm),
        deliverable_dir="e2e_flat",
        sandbox=WorkspaceSandbox(tmp_path),
        release_requested=True,
        auto_release=True,
    )
    plan = orchestrator.create_plan("开发一个待办事项 CLI 工具")
    orchestrator.execute(orchestrator.build_task_manager(plan))

    delivery = orchestrator.last_delivery
    assert delivery["integration"]["status"] == "failed"
    assert delivery["release"] is None
    assert delivery["package"] is None


STATIC_BUG_TODO = "MESSAGE = 'ok'\n\nif False:\n    print(MISSING_NAME)\n"


def test_static_gate_failure_triggers_rework_round(tmp_path: Path):
    # The suite alone would pass: the ruff-enforced undefined name drives the round.
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=STATIC_BUG_TODO, rework_fixes=True)

    delivery = _run_project(tmp_path, developer)[1]

    integration = delivery["integration"]
    assert integration["status"] == "passed"
    assert integration["rounds"] == 1
    assert integration["static"]["status"] == "passed"
    assert "static" in developer.rework_calls[0].context["integration_failure"]
    assert delivery["package"] is not None


def test_static_gate_can_be_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_TEAM_STATIC_GATE", "0")
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=STATIC_BUG_TODO, rework_fixes=False)

    delivery = _run_project(tmp_path, developer)[1]

    integration = delivery["integration"]
    assert integration["status"] == "passed"
    assert integration["rounds"] == 0
    assert integration["static"] is None


def test_invalid_round_configuration_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_TEAM_INTEGRATION_MAX_ROUNDS", "-1")
    developer = _DeveloperStub(tmp_path / "e2e_flat", initial=GOOD_TODO, rework_fixes=False)

    with pytest.raises(ValueError, match="AI_TEAM_INTEGRATION_MAX_ROUNDS"):
        _run_project(tmp_path, developer)
