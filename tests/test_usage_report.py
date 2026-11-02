"""Run-level model usage attribution and delivery cost-report contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.analyst import RequirementAnalystAgent
from agents.doc_writer import DocWriterAgent
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_config import AgentConfig
from runtime.agent_factory import create_agent_router
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.base import BaseLLM
from runtime.model_governance import ModelUsage
from runtime.model_usage import ModelUsageLedger
from runtime.task import Task
from security.workspace import WorkspaceSandbox


def test_factory_wires_usage_ledger_into_every_role_llm():
    ledger = ModelUsageLedger()
    router = create_agent_router(usage_ledger=ledger, usage_project_id="run-test")

    for role in ("analyst", "architect", "tester", "planner", "doc_writer", "qa", "reviewer"):
        agent = router.get_agent(role)
        assert getattr(agent.llm, "usage_ledger", None) is ledger, role


def test_factory_without_ledger_leaves_llms_unattributed():
    router = create_agent_router()

    agent = router.get_agent("analyst")
    assert getattr(agent.llm, "usage_ledger", None) is None


def test_factory_rejects_project_id_without_ledger():
    with pytest.raises(ValueError, match="usage_ledger is required"):
        create_agent_router(usage_project_id="run-test")


ANALYSIS_MARKDOWN = """# 需求规格说明（草案）

## 一、项目概述
词频统计工具。

## 二、功能需求清单
### REQ-001 词频统计（必须）
统计单词出现次数。
验收标准：输出与样例一致。

## 三、非功能需求
-【假设】UTF-8 输入。

## 四、验收标准
见 REQ-001。

## 五、假设与约束
-【假设】单机运行。

## 六、待确认问题
无。
"""


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
                "project": "wordcount",
                "summary": "词频统计工具",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "实现 wordcount.py",
                        "description": "在 e2e_flat/ 下实现词频统计",
                        "role": "developer",
                        "dependencies": [],
                    }
                ],
            }
        }


class _CompletedStubAgent:
    def __init__(self, role: str) -> None:
        self._role = role

    @property
    def role(self) -> str:
        return self._role

    def run(self, task: Task) -> AgentResult:
        return AgentResult(status="completed", agent=self.role, task_id=task.id, message="ok")


class _WritingDeveloperStub:
    role = "developer"

    def __init__(self, deliverable: Path) -> None:
        self._deliverable = deliverable

    def run(self, task: Task) -> AgentResult:
        self._deliverable.mkdir(parents=True, exist_ok=True)
        (self._deliverable / "wordcount.py").write_text("def count(text):\n    return {}\n", encoding="utf-8")
        return AgentResult(status="completed", agent="developer", task_id=task.id, message="ok")


def _run(tmp_path: Path, ledger: ModelUsageLedger | None, project_id: str | None):
    doc_llm = _FixedTextLLM("# 测试结果报告\n\nok\n")
    router = AgentRouter()
    router.register("analyst", RequirementAnalystAgent(
        AgentConfig(role="analyst", model=""), llm=_FixedTextLLM(ANALYSIS_MARKDOWN),
    ))
    router.register("planner", _StubPlanner())
    router.register("developer", _WritingDeveloperStub(tmp_path / "e2e_flat"))
    router.register("tester", _CompletedStubAgent("tester"))
    router.register("reviewer", _CompletedStubAgent("reviewer"))
    router.register("doc_writer", DocWriterAgent(
        AgentConfig(role="doc_writer", model=""), llm=doc_llm, sandbox=WorkspaceSandbox(tmp_path),
    ))
    orchestrator = ProjectOrchestrator(
        agent_router=router,
        deliverable_dir="e2e_flat",
        sandbox=WorkspaceSandbox(tmp_path),
        usage_ledger=ledger,
        usage_project_id=project_id,
    )
    plan = orchestrator.create_plan("统计文本词频")
    orchestrator.execute(orchestrator.build_task_manager(plan))
    return orchestrator, doc_llm


def test_usage_report_flows_into_delivery_and_docs(tmp_path: Path):
    ledger = ModelUsageLedger()
    ledger.record("run-x", ModelUsage(input_tokens=100, output_tokens=20, llm_calls=2))

    orchestrator, doc_llm = _run(tmp_path, ledger, "run-x")
    delivery = orchestrator.last_delivery

    assert delivery["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "llm_calls": 2,
        "cost_usd": None,
    }
    assert any("模型用量与成本" in prompt for prompt in doc_llm.prompts)
    assert any("- LLM 调用次数: 2" in prompt for prompt in doc_llm.prompts)


def test_delivery_without_ledger_has_no_usage_report(tmp_path: Path):
    orchestrator, doc_llm = _run(tmp_path, None, None)

    assert orchestrator.last_delivery["usage"] is None
    assert not any("模型用量与成本" in prompt for prompt in doc_llm.prompts)
