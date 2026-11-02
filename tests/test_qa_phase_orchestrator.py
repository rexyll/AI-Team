"""Orchestrator-level QA phase contracts.

The product-level QA phase runs once after the integration gate and before
documentation. A QA_FAILED verdict blocks the release honestly but never
blocks packaging; without a registered qa agent the phase is a no-op.
"""

from __future__ import annotations

from pathlib import Path

from agents.analyst import RequirementAnalystAgent
from agents.doc_writer import DocWriterAgent
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_config import AgentConfig
from runtime.agent_result import AgentResult
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
    def __init__(self, role: str, status: str, message: str) -> None:
        self._role = role
        self._status = status
        self._message = message

    @property
    def role(self) -> str:
        return self._role

    def run(self, task: Task) -> dict:
        return {
            "status": self._status,
            "agent": self._role,
            "task_id": task.id,
            "message": self._message,
        }


class _DeveloperStub:
    role = "developer"

    def __init__(self, deliverable: Path) -> None:
        self._deliverable = deliverable

    def run(self, task: Task) -> dict:
        self._deliverable.mkdir(parents=True, exist_ok=True)
        (self._deliverable / "todo.py").write_text(GOOD_TODO, encoding="utf-8")
        (self._deliverable / "test_todo.py").write_text(TODO_TEST, encoding="utf-8")
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implemented",
        }


class _StubQAAgent:
    role = "qa"

    def __init__(self, message: str) -> None:
        self._message = message
        self.calls: list[Task] = []

    def run(self, task: Task) -> AgentResult:
        self.calls.append(task)
        verdict = self._message.splitlines()[0].strip()
        return AgentResult(
            status="completed",
            agent="qa",
            task_id=task.id,
            message=self._message,
            data={"qa": {"verdict": verdict, "executed_tool_calls": 0}},
        )


def _router(tmp_path: Path, qa_agent: _StubQAAgent | None) -> AgentRouter:
    router = AgentRouter()
    router.register("analyst", RequirementAnalystAgent(
        AgentConfig(role="analyst", model=""), llm=_FixedTextLLM(ANALYSIS_MARKDOWN),
    ))
    router.register("planner", _StubPlanner())
    router.register("developer", _DeveloperStub(tmp_path / "e2e_flat"))
    router.register("tester", _DictStubAgent("tester", "passed", "TEST_PASSED"))
    router.register("reviewer", _DictStubAgent("reviewer", "approved", "APPROVED"))
    router.register("doc_writer", DocWriterAgent(
        AgentConfig(role="doc_writer", model=""), llm=_FixedTextLLM("# 测试结果报告\n\nok\n"), sandbox=WorkspaceSandbox(tmp_path),
    ))
    if qa_agent is not None:
        router.register("qa", qa_agent)
    return router


def _run(tmp_path: Path, qa_agent: _StubQAAgent | None, *, release: bool = False):
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path, qa_agent),
        deliverable_dir="e2e_flat",
        sandbox=WorkspaceSandbox(tmp_path),
        release_requested=release,
        auto_release=True,
    )
    plan = orchestrator.create_plan("开发一个待办事项 CLI 工具")
    orchestrator.execute(orchestrator.build_task_manager(plan))
    return orchestrator, orchestrator.last_delivery


def test_qa_phase_passes_and_evidence_reaches_docs(tmp_path: Path):
    qa_agent = _StubQAAgent("QA_PASSED\n用例 1：空输入被拒绝。")

    orchestrator, delivery = _run(tmp_path, qa_agent)

    qa = delivery["qa"]
    assert qa["verdict"] == "QA_PASSED"
    assert qa["status"] == "completed"
    assert len(qa_agent.calls) == 1
    assert qa_agent.calls[0].context["deliverable_dir"] == "e2e_flat"
    # The doc writer received the QA evidence section.
    doc_writer = orchestrator.agent_router.get_agent("doc_writer")
    assert any("QA 对抗测试" in prompt for prompt in doc_writer.llm.prompts)
    assert delivery["package"] is not None


def test_qa_failure_blocks_release_but_not_packaging(tmp_path: Path):
    delivery = _run(tmp_path, _StubQAAgent("QA_FAILED\n空输入导致程序崩溃。"), release=True)[1]

    assert delivery["qa"]["verdict"] == "QA_FAILED"
    assert delivery["release"] == {"status": "blocked", "reason": "QA verdict is QA_FAILED"}
    # Packaging still proceeds; the finding is reported, not hidden.
    assert delivery["package"] is not None


def test_qa_phase_is_noop_without_qa_agent(tmp_path: Path):
    _, delivery = _run(tmp_path, None, release=True)

    assert delivery["qa"] is None
    assert delivery["release"]["status"] == "released"
    assert delivery["package"] is not None
