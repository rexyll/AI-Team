"""QA adversarial agent: verdict parsing, advisory semantics, workflow wiring."""
from __future__ import annotations

import pytest

from agents.qa import QAAdversarialAgent
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter
from runtime.context_builder import ContextBuilder
from runtime.llm.base import BaseLLM
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class _FixedLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("QA has no tools")


def _qa_agent(text: str) -> QAAdversarialAgent:
    return QAAdversarialAgent(AgentConfig(role="qa", model=""), llm=_FixedLLM(text))


def _task() -> Task:
    return Task(id="T1", title="t", description="d", role="developer", status="ready")


@pytest.mark.parametrize("raw,verdict", [
    ("QA_CLEAN\n未发现问题。", "clean"),
    ("QA_CONCERNS\n1. 空输入未处理（已证实）", "concerns"),
])
def test_verdict_parsing(raw, verdict):
    agent = _qa_agent(raw)
    result = agent.run(_task())

    # Advisory stage: workflow status is always completed; verdict rides in data.
    assert result.status == "completed"
    assert result.data["verdict"] == verdict


def test_invalid_verdict_raises():
    agent = _qa_agent("我觉得没问题")
    with pytest.raises(ValueError, match="QA_CONCERNS or QA_CLEAN"):
        agent.run(_task())


def test_prompt_carries_task_and_developer_evidence():
    agent = _qa_agent("QA_CLEAN\nok")
    task = _task()
    task.result = {"message": "done", "data": {"tests": [{"command": "pytest"}]}}
    context = ContextBuilder().build_agent_context(task, role="qa")
    # BaseAgent.build_context is driven by the workflow; drive the prompt directly.
    prompt = QAAdversarialAgent._build_prompt(context)

    assert "T1" in prompt
    assert "done" in prompt
    assert "pytest" in prompt
    # The tester verdict section exists even when empty.
    assert "tester.feedback" in prompt


def test_workflow_stores_qa_feedback_and_task_completes():
    class FakeReviewer:
        role = "reviewer"

        def run(self, task):
            from runtime.agent_result import AgentResult
            assert "qa_feedback" in task.context, "reviewer must see qa feedback"
            return AgentResult(status="approved", agent="reviewer", task_id=task.id, message="ok")

    class FakeDeveloper:
        role = "developer"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="completed", agent="developer", task_id=task.id, message="dev ok")

    class FakeTester:
        role = "tester"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="passed", agent="tester", task_id=task.id, message="TEST_PASSED\nok")

    class FakeQA:
        role = "qa"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="completed", agent="qa", task_id=task.id, message="QA_CONCERNS\n边界未覆盖（疑似）", data={"verdict": "concerns", "summary": "x"})

    router = AgentRouter()
    router.register("developer", FakeDeveloper())
    router.register("tester", FakeTester())
    router.register("reviewer", FakeReviewer())
    router.register("qa", FakeQA())

    manager = TaskManager([_task()])
    workflow = TaskWorkflow(
        task_manager=manager, developer=router.get_agent("developer"),
        reviewer=router.get_agent("reviewer"), agent_router=router,
    )
    task = workflow.execute("T1")

    assert task.status == "completed"
    feedback = task.context["qa_feedback"]
    assert feedback["status"] == "completed"
    assert feedback["data"]["verdict"] == "concerns"


def test_qa_failure_does_not_fail_the_task():
    class FakeReviewer:
        role = "reviewer"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="approved", agent="reviewer", task_id=task.id, message="ok")

    class FakeDeveloper:
        role = "developer"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="completed", agent="developer", task_id=task.id, message="dev ok")

    class FakeTester:
        role = "tester"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="passed", agent="tester", task_id=task.id, message="TEST_PASSED\nok")

    class BrokenQA:
        role = "qa"

        def run(self, task):
            raise RuntimeError("qa provider down")

    router = AgentRouter()
    router.register("developer", FakeDeveloper())
    router.register("tester", FakeTester())
    router.register("reviewer", FakeReviewer())
    router.register("qa", BrokenQA())

    manager = TaskManager([_task()])
    workflow = TaskWorkflow(
        task_manager=manager, developer=router.get_agent("developer"),
        reviewer=router.get_agent("reviewer"), agent_router=router,
    )
    task = workflow.execute("T1")

    # Advisory stage degrades to skipped; the verified product still completes.
    assert task.status == "completed"
    assert "qa_feedback" not in task.context


def test_no_qa_agent_leaves_feedback_absent():
    class FakeReviewer:
        role = "reviewer"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="approved", agent="reviewer", task_id=task.id, message="ok")

    class FakeDeveloper:
        role = "developer"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="completed", agent="developer", task_id=task.id, message="dev ok")

    class FakeTester:
        role = "tester"

        def run(self, task):
            from runtime.agent_result import AgentResult
            return AgentResult(status="passed", agent="tester", task_id=task.id, message="TEST_PASSED\nok")

    router = AgentRouter()
    router.register("developer", FakeDeveloper())
    router.register("tester", FakeTester())
    router.register("reviewer", FakeReviewer())

    manager = TaskManager([_task()])
    workflow = TaskWorkflow(
        task_manager=manager, developer=router.get_agent("developer"),
        reviewer=router.get_agent("reviewer"), agent_router=router,
    )
    task = workflow.execute("T1")

    assert task.status == "completed"
    assert "qa_feedback" not in task.context


def test_reviewer_prompt_includes_qa_findings():
    from agents.reviewer import ReviewerAgent

    class CaptureLLM(_FixedLLM):
        pass

    llm = CaptureLLM("approved\nok")
    reviewer = ReviewerAgent(AgentConfig(role="reviewer", model=""), llm=llm)
    task = _task()
    task.result = {"message": "done"}
    task.context["qa_feedback"] = {"data": {"verdict": "concerns", "summary": "QA_CONCERNS\n空输入未处理（已证实）"}}
    context = ContextBuilder({task.id: task}).build_agent_context(task, role="reviewer")
    prompt = reviewer._build_prompt(context) if hasattr(reviewer, "_build_prompt") else None

    if prompt is None:
        pytest.skip("reviewer prompt builder not directly accessible")
    assert "qa.feedback" in prompt
