import ast
from pathlib import Path

from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


WORKFLOW_SOURCE = Path("runtime/workflow.py").read_text(encoding="utf-8")


class LLMIndependentDeveloper:
    role = "developer"

    def run(self, task):
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implemented",
        }


class LLMIndependentTester:
    role = "tester"

    def run(self, task):
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "TEST_PASSED",
        }


class LLMIndependentReviewer:
    role = "reviewer"

    def run(self, task):
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "APPROVED",
        }


def test_workflow_has_no_provider_or_ask_ai_dependency():
    tree = ast.parse(WORKFLOW_SOURCE)

    imported_modules = set()
    imported_names = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
            imported_names.update(alias.name for alias in node.names)

    assert "config.model" not in imported_modules
    assert "runtime.llm.provider" not in imported_modules
    assert "ask_ai" not in imported_names
    assert "ProviderLLM" not in imported_names


def test_workflow_executes_with_agents_that_have_no_llm_attribute():
    task = Task(
        id="TASK-WF-LLM-001",
        title="workflow dependency inversion",
        description="Verify workflow depends only on agent execution contracts.",
        role="developer",
        status="ready",
    )

    developer = LLMIndependentDeveloper()
    tester = LLMIndependentTester()
    reviewer = LLMIndependentReviewer()

    router = AgentRouter()
    router.register("developer", developer)
    router.register("tester", tester)
    router.register("reviewer", reviewer)

    manager = TaskManager([task])
    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=router,
    )

    assert not hasattr(developer, "llm")
    assert not hasattr(tester, "llm")
    assert not hasattr(reviewer, "llm")

    result = workflow.execute(task.id)

    assert result.status == "completed"
    assert result.test_result["status"] == "passed"
    assert result.review_result["status"] == "approved"


def test_workflow_accepts_arbitrary_agent_execution_implementation():
    task = Task(
        id="TASK-WF-LLM-002",
        title="workflow contract",
        description="Verify workflow does not require a concrete LLM implementation.",
        role="developer",
        status="ready",
    )

    developer = LLMIndependentDeveloper()
    reviewer = LLMIndependentReviewer()

    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)

    manager = TaskManager([task])
    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=None,
        reviewer=reviewer,
        agent_router=router,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"
    assert result.review_result["status"] == "approved"
