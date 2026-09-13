"""Orchestrator-level delivery pipeline contracts.

The requirement analyst runs before the planner (its structured draft rides
along with the original requirement text), and the documentation + manifest
phase runs after every product task completes. Core workflow semantics stay
untouched: both phases are project-level orchestration steps.
"""

from __future__ import annotations

from pathlib import Path

from agents.analyst import RequirementAnalystAgent
from agents.doc_writer import DocWriterAgent, DOC_SPECS
from runtime.agent_config import AgentConfig
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.base import BaseLLM
from core.project_orchestrator import ProjectOrchestrator
from runtime.task import Task
from runtime.task_manager import TaskManager
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
1. 是否需要导出 CSV？
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
    last_description: str | None = None

    def run(self, task: Task) -> dict:
        _StubPlanner.last_description = task.description
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


def _router(tmp_path: Path) -> AgentRouter:
    router = AgentRouter()
    router.register("analyst", RequirementAnalystAgent(
        AgentConfig(role="analyst", model=""), llm=_FixedTextLLM(ANALYSIS_MARKDOWN),
    ))
    router.register("planner", _StubPlanner())
    router.register("developer", _CompletedStubAgent("developer"))
    router.register("tester", _CompletedStubAgent("tester"))
    router.register("reviewer", _CompletedStubAgent("reviewer"))
    router.register("doc_writer", DocWriterAgent(
        AgentConfig(role="doc_writer", model=""), llm=_FixedTextLLM("# 文档\n\nREQ-001 已实现并通过验收。\n"), sandbox=WorkspaceSandbox(tmp_path),
    ))
    return router


def test_create_plan_passes_analysis_via_context(tmp_path: Path):
    orchestrator = ProjectOrchestrator(agent_router=_router(tmp_path), deliverable_dir="e2e_flat")

    plan = orchestrator.create_plan("统计文本词频")

    assert plan["project"] == "wordcount"
    assert orchestrator.last_requirement_analysis is not None
    assert "REQ-001" in orchestrator.last_requirement_analysis
    # The planner's description stays the pure user requirement: mechanical
    # path-constraint extraction must never see analyst-side text (a live run
    # showed analyst-hallucinated directories becoming enforced constraints).
    assert _StubPlanner.last_description == "统计文本词频"


def test_delivery_phase_writes_docs_and_manifest(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)
    orchestrator = ProjectOrchestrator(agent_router=_router(tmp_path), deliverable_dir="e2e_flat", sandbox=sandbox)
    plan = orchestrator.create_plan("统计文本词频")
    task_manager = orchestrator.build_task_manager(plan)
    task_manager.mark_ready("TASK-001")
    task_manager.mark_running("TASK-001")
    task_manager.record_result("TASK-001", {"message": "实现完成", "data": {"tests": [{"command": "python -m pytest"}]}})
    task_manager.mark_completed("TASK-001")

    delivery = orchestrator._run_delivery_phase(task_manager, project="wordcount")

    assert delivery is not None
    assert len(delivery["docs"]) == len(DOC_SPECS)
    docs_dir = tmp_path / "e2e_flat" / "docs"
    for spec in DOC_SPECS:
        assert (docs_dir / spec[0]).is_file()
    manifest = tmp_path / "e2e_flat" / "DELIVERY_MANIFEST.md"
    assert manifest.is_file()
    assert "docs/requirements.md" in manifest.read_text(encoding="utf-8")
    package = delivery["package"]
    assert package["files"] >= 6  # code + docs + manifest
    assert Path(package["archive"]).is_file()
    assert delivery["smoke"]["status"] in {"passed", "skipped"}


def test_delivery_phase_is_noop_without_doc_writer(tmp_path: Path):
    router = _router(tmp_path)
    router.agents.pop("doc_writer")
    orchestrator = ProjectOrchestrator(agent_router=router)
    task_manager = TaskManager([Task(id="TASK-001", title="t", description="d", role="developer", status="completed")])

    assert orchestrator._run_delivery_phase(task_manager, project=None) is None
    assert orchestrator.last_delivery is None


def test_acceptance_runs_after_delivery_and_passes(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)
    orchestrator = ProjectOrchestrator(agent_router=_router(tmp_path), deliverable_dir="e2e_flat", sandbox=sandbox)
    plan = orchestrator.create_plan("统计文本词频")
    task_manager = orchestrator.build_task_manager(plan)
    task_manager.mark_ready("TASK-001")
    task_manager.mark_running("TASK-001")
    task_manager.record_result("TASK-001", {"message": "实现完成 REQ-001", "data": {"tests": []}})
    task_manager.mark_completed("TASK-001")

    delivery = orchestrator._run_delivery_phase(task_manager, project="wordcount")

    assert delivery is not None
    acceptance = delivery["acceptance"]
    assert acceptance is not None
    assert acceptance["verdict"] == "passed"
    assert acceptance["total_requirements"] >= 1
    report = Path(acceptance["report"])
    assert report.is_file()
    assert "验收结论：**PASSED**" in report.read_text(encoding="utf-8")
    assert orchestrator.last_acceptance is acceptance


def test_orchestrator_passes_clarifications_to_analyst(tmp_path: Path):
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path),
        deliverable_dir="e2e_flat",
        clarifications="1. 中文分词：不支持，按空格分词。",
    )

    orchestrator.create_plan("统计文本词频")

    analyst = orchestrator.agent_router.get_agent("analyst")
    assert analyst.llm.prompts  # analyst was invoked
    prompt = analyst.llm.prompts[0]
    assert 'source="customer.clarifications"' in prompt
    assert "按空格分词" in prompt
