import ast
from pathlib import Path

from agents.base import BaseAgent
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.base import BaseLLM
from runtime.llm.mock import MockLLM
from runtime.llm.provider import ProviderLLM
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


WORKFLOW_SOURCE = Path("runtime/workflow.py").read_text(encoding="utf-8")


class FakeProviderClient:
    class _Completions:
        def __init__(self, response: str):
            self.response = response
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(dict(kwargs))

            class Message:
                content = self.response

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class _Chat:
        def __init__(self, response: str):
            self.completions = FakeProviderClient._Completions(response)

    def __init__(self, response: str = "PROVIDER_RESPONSE"):
        self.chat = self._Chat(response)


class LLMBackedAgent(BaseAgent):
    """Minimal real Agent contract used to prove LLM substitution."""

    def __init__(self, role: str, *, llm: BaseLLM):
        self._role = role
        super().__init__(llm=llm)

    @property
    def role(self) -> str:
        return self._role

    def run(self, task: Task) -> AgentResult:
        response = self.llm.generate(
            f"execute {task.id}",
            system_prompt=f"role={self.role}",
        )

        status = {
            "developer": "completed",
            "tester": "passed",
            "reviewer": "approved",
        }[self.role]

        return AgentResult(
            status=status,
            agent=self.role,
            task_id=task.id,
            message=response,
        )


def _build_workflow(llm_factory):
    task = Task(
        id="TASK-CONFIG-001",
        title="provider substitution",
        description="Verify LLM implementation substitution.",
        role="developer",
        status="ready",
    )

    developer = LLMBackedAgent("developer", llm=llm_factory("developer"))
    tester = LLMBackedAgent("tester", llm=llm_factory("tester"))
    reviewer = LLMBackedAgent("reviewer", llm=llm_factory("reviewer"))

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

    return workflow, task


def test_same_agent_contract_accepts_different_llm_implementations():
    mock_agent = LLMBackedAgent(
        "developer",
        llm=MockLLM("mock-response"),
    )
    provider_client = FakeProviderClient("provider-response")
    provider_agent = LLMBackedAgent(
        "developer",
        llm=ProviderLLM(
            model="provider-model-a",
            client_instance=provider_client,
        ),
    )

    task = Task(
        id="TASK-CONFIG-002",
        title="substitution",
        description="Verify one Agent can use different LLM implementations.",
        role="developer",
    )

    mock_result = mock_agent.run(task)
    provider_result = provider_agent.run(task)

    assert mock_result.status == "completed"
    assert mock_result.message == "mock-response"
    assert provider_result.status == "completed"
    assert provider_result.message == "provider-response"
    assert isinstance(mock_agent.llm, BaseLLM)
    assert isinstance(provider_agent.llm, BaseLLM)


def test_provider_configuration_is_local_to_provider_adapter():
    client_a = FakeProviderClient("A")
    client_b = FakeProviderClient("B")

    provider_a = ProviderLLM(
        model="model-a",
        client_instance=client_a,
    )
    provider_b = ProviderLLM(
        model="model-b",
        client_instance=client_b,
    )

    assert provider_a.model == "model-a"
    assert provider_b.model == "model-b"
    assert provider_a.generate("hello") == "A"
    assert provider_b.generate("hello") == "B"

    assert client_a.chat.completions.calls[0]["model"] == "model-a"
    assert client_b.chat.completions.calls[0]["model"] == "model-b"


def test_same_workflow_execution_path_works_with_mock_and_provider_llm():
    mock_workflow, mock_task = _build_workflow(
        lambda role: MockLLM(f"mock-{role}")
    )

    provider_clients = {}

    def provider_factory(role):
        client = FakeProviderClient(f"provider-{role}")
        provider_clients[role] = client
        return ProviderLLM(
            model=f"model-{role}",
            client_instance=client,
        )

    provider_workflow, provider_task = _build_workflow(provider_factory)

    mock_result = mock_workflow.execute(mock_task.id)
    provider_result = provider_workflow.execute(provider_task.id)

    assert mock_result.status == "completed"
    assert provider_result.status == "completed"
    assert mock_result.test_result["status"] == "passed"
    assert provider_result.test_result["status"] == "passed"
    assert mock_result.review_result["status"] == "approved"
    assert provider_result.review_result["status"] == "approved"

    for role, client in provider_clients.items():
        assert client.chat.completions.calls
        assert client.chat.completions.calls[0]["model"] == f"model-{role}"


def test_workflow_does_not_branch_on_provider_configuration():
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
    assert "ProviderLLM" not in imported_names
    assert "AGNES_MODEL" not in imported_names
    assert "AGNES_API_KEY" not in imported_names
    assert "provider" not in {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }


def test_agent_llm_injection_rejects_non_base_llm_implementations():
    try:
        LLMBackedAgent("developer", llm=object())  # type: ignore[arg-type]
    except TypeError as exc:
        assert "BaseLLM" in str(exc)
    else:
        raise AssertionError("BaseAgent must reject non-BaseLLM dependencies")
