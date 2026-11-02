"""Change-request intake contracts: authoritative CHG amendments via the analyst."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.analyst import RequirementAnalystAgent, run_quality_checked_analysis
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_config import AgentConfig
from runtime.llm.base import BaseLLM
from runtime.task import Task
from security.workspace import WorkspaceSandbox

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

CHANGE_REQUEST = """变更 1（CHG-001）：新增导出 CSV 功能。
变更 2（CHG-002）：删除大小写归一化。
"""


class _CapturingLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("not used")


def _analyst(llm: _CapturingLLM) -> RequirementAnalystAgent:
    return RequirementAnalystAgent(AgentConfig(role="analyst", model=""), llm=llm)


def test_analyst_prompt_receives_fenced_change_request():
    llm = _CapturingLLM(ANALYSIS_MARKDOWN)

    run_quality_checked_analysis(_analyst(llm), requirement="统计文本词频", change_request=CHANGE_REQUEST)

    prompt = llm.prompts[0]
    assert 'source="customer.change_request"' in prompt
    assert "CHG-001" in prompt
    assert "变更受理要求" in prompt
    assert "客户需求变更请求（权威修订" in prompt


def test_analyst_runs_without_change_request():
    llm = _CapturingLLM(ANALYSIS_MARKDOWN)

    result = run_quality_checked_analysis(_analyst(llm), requirement="统计文本词频")

    assert 'source="customer.change_request"' not in llm.prompts[0]
    assert result.data["change_request_applied"] is False


def test_agent_run_applies_change_request_context():
    llm = _CapturingLLM(ANALYSIS_MARKDOWN)
    agent = _analyst(llm)
    task = Task(id="REQ-ANALYSIS", title="t", description="统计文本词频", role="analyst", status="ready")
    task.context["customer_change_request"] = CHANGE_REQUEST

    result = agent.run(task)

    assert result.data["change_request_applied"] is True
    assert 'source="customer.change_request"' in llm.prompts[0]


def test_orchestrator_passes_change_request_to_analyst(tmp_path: Path):
    llm = _CapturingLLM(ANALYSIS_MARKDOWN)
    router_router = ProjectOrchestrator(
        agent_router=_stub_router(llm),
        deliverable_dir="e2e_flat",
        change_request=CHANGE_REQUEST,
    )

    router_router.create_plan("统计文本词频")

    analyst = router_router.agent_router.get_agent("analyst")
    assert 'source="customer.change_request"' in analyst.llm.prompts[0]
    assert "CHG-002" in analyst.llm.prompts[0]


def test_orchestrator_rejects_non_string_change_request():
    with pytest.raises(TypeError, match="change_request"):
        ProjectOrchestrator(
            agent_router=_stub_router(_CapturingLLM(ANALYSIS_MARKDOWN)),
            change_request=123,
        )


def _stub_router(llm: _CapturingLLM):
    from runtime.agent_router import AgentRouter

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

    router = AgentRouter()
    router.register("analyst", RequirementAnalystAgent(AgentConfig(role="analyst", model=""), llm=llm))
    router.register("planner", _StubPlanner())
    return router


def test_main_rejects_empty_change_request_file(tmp_path: Path):
    import main as main_module

    empty = tmp_path / "change.md"
    empty.write_text("   \n", encoding="utf-8")

    with pytest.raises(ValueError, match="change request file cannot be empty"):
        main_module.read_change_request(str(empty))


def test_main_reads_change_request_file(tmp_path: Path):
    import main as main_module

    change = tmp_path / "change.md"
    change.write_text("CHG-001: 新增导出\n", encoding="utf-8")

    assert main_module.read_change_request(str(change)) == "CHG-001: 新增导出\n"
    assert main_module.read_change_request(None) is None


def test_project_orchestrator_sandbox_param_combines_with_change_request(tmp_path: Path):
    orchestrator = ProjectOrchestrator(
        agent_router=_stub_router(_CapturingLLM(ANALYSIS_MARKDOWN)),
        deliverable_dir="e2e_flat",
        sandbox=WorkspaceSandbox(tmp_path),
        change_request=CHANGE_REQUEST,
    )

    assert orchestrator.change_request == CHANGE_REQUEST
