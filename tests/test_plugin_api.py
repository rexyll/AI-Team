import pytest

from agents.base import BaseAgent
from runtime.agent_config import AgentConfig
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.base import BaseLLM
from runtime.plugin_agent_adapter import PluginAgentInvocationAdapter
from runtime.plugin_api import (
    AGENT_EXTENSION_POINT,
    PLUGIN_API_VERSION,
    PluginError,
    PluginHost,
    PluginLifecycleError,
    PluginMetadata,
    TOOL_EXTENSION_POINT,
    WORKFLOW_EXTENSION_POINT,
)
from runtime.plugin_tool_adapter import PluginToolInvocationAdapter
from runtime.plugin_workflow_adapter import PluginWorkflowInvocationAdapter
from runtime.task import Task
from runtime.tool_invocation_service import ToolInvocationService
from runtime.workflow import TaskWorkflow
from tools.registry import ToolRegistry


class _Context:
    def __init__(self, *capabilities, extensions=None):
        self.capabilities = set(capabilities)
        self.extensions = dict(extensions or {})

    def has_capability(self, capability):
        return capability in self.capabilities

    def get_extension(self, extension_point):
        return self.extensions.get(extension_point)


class _Plugin:
    metadata = PluginMetadata("demo", "1.0", capabilities=frozenset({"observe"}))

    def __init__(self):
        self.calls = []

    def initialize(self, context):
        self.calls.append("initialize")

    def shutdown(self):
        self.calls.append("shutdown")


class _NoOpLLM(BaseLLM):
    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        return "ok"


class _Agent(BaseAgent):
    def __init__(self, role: str, result_data: dict | None = None):
        super().__init__(AgentConfig(role=role, model=""), llm=_NoOpLLM())
        self._role = role
        self.result_data = result_data or {}
        self.received_tasks = []

    @property
    def role(self):
        return self._role

    def run(self, task: Task) -> AgentResult:
        self.received_tasks.append(task)
        task.context["mutated_by_agent"] = True
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            data=self.result_data,
        )


def test_plugin_metadata_has_versioned_contract():
    metadata = PluginMetadata("demo", "1.0", capabilities=frozenset({"observe"}))
    assert metadata.api_version == PLUGIN_API_VERSION


def test_registration_rejects_undelegated_capability():
    with pytest.raises(PermissionError, match="denied capabilities"):
        PluginHost().register(_Plugin())


def test_lifecycle_requires_host_and_context_capability():
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}))
    host.register(plugin)
    with pytest.raises(PermissionError, match="not granted"):
        host.initialize("demo", _Context())
    host.initialize("demo", _Context("observe"))
    host.shutdown("demo")
    assert plugin.calls == ["initialize", "shutdown"]


def test_initialize_is_guarded_against_double_start():
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}))
    host.register(plugin)
    host.initialize("demo", _Context("observe"))
    with pytest.raises(PluginLifecycleError, match="already initialized"):
        host.initialize("demo", _Context("observe"))


def test_list_plugins_returns_metadata_only():
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}))
    host.register(plugin)
    assert host.list_plugins() == (plugin.metadata,)


def test_extension_point_must_be_hosted_and_context_bound():
    extension = object()
    metadata = PluginMetadata(
        "extension-demo",
        "1.0",
        extension_points=frozenset({"dashboard"}),
    )

    class ExtensionPlugin(_Plugin):
        pass

    plugin = ExtensionPlugin()
    plugin.metadata = metadata

    with pytest.raises(PluginError, match="unavailable extension points"):
        PluginHost().register(plugin)

    host = PluginHost(extensions={"dashboard": extension})
    host.register(plugin)
    with pytest.raises(PermissionError, match="not provided by host context"):
        host.initialize("extension-demo", _Context())
    host.initialize("extension-demo", _Context(extensions={"dashboard": extension}))
    assert plugin.calls == ["initialize"]


def test_tools_extension_rejects_raw_tool_registry():
    metadata = PluginMetadata(
        "raw-tools",
        "1.0",
        extension_points=frozenset({TOOL_EXTENSION_POINT}),
    )
    plugin = _Plugin()
    plugin.metadata = metadata

    with pytest.raises(PluginError, match="tools extension must be a PluginToolInvocationAdapter"):
        PluginHost(extensions={TOOL_EXTENSION_POINT: ToolRegistry()}).register(plugin)


def test_tools_extension_requires_canonical_invocation_adapter():
    metadata = PluginMetadata(
        "safe-tools",
        "1.0",
        extension_points=frozenset({TOOL_EXTENSION_POINT}),
    )
    plugin = _Plugin()
    plugin.metadata = metadata
    service = ToolInvocationService()
    adapter = PluginToolInvocationAdapter(service, role="developer")
    host = PluginHost(extensions={TOOL_EXTENSION_POINT: adapter})

    host.register(plugin)
    host.initialize("safe-tools", _Context(extensions={TOOL_EXTENSION_POINT: adapter}))
    assert plugin.calls == ["initialize"]
    assert adapter.role == "developer"


def test_plugin_tool_adapter_binds_role_and_preserves_runtime_result_boundary():
    service = ToolInvocationService()
    adapter = PluginToolInvocationAdapter(service, role="reviewer")

    result = adapter.invoke(
        task_id="TASK-PLUGIN-001",
        execution_id="EXEC-PLUGIN-001",
        tool_name="write_file",
        arguments={"path": "README.md", "content": "should-not-write"},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_PERMISSION_DENIED"
    assert service.audit.count() == 1
    record = service.audit.records()[0]
    assert record.agent_role == "reviewer"
    assert record.tool_name == "write_file"


def test_plugin_tool_adapter_cannot_override_host_assigned_role():
    service = ToolInvocationService()
    adapter = PluginToolInvocationAdapter(service, role="architect")

    with pytest.raises(TypeError):
        adapter.invoke(
            role="developer",
            task_id="TASK-PLUGIN-002",
            execution_id="EXEC-PLUGIN-002",
            tool_name="read_file",
            arguments={"path": "README.md"},
        )


def test_agents_extension_rejects_raw_router():
    metadata = PluginMetadata(
        "raw-agents",
        "1.0",
        extension_points=frozenset({AGENT_EXTENSION_POINT}),
    )
    plugin = _Plugin()
    plugin.metadata = metadata
    router = AgentRouter()
    router.register(_Agent("architect"))

    with pytest.raises(PluginError, match="agents extension must be a PluginAgentInvocationAdapter"):
        PluginHost(extensions={AGENT_EXTENSION_POINT: router}).register(plugin)


def test_agents_extension_requires_canonical_invocation_adapter():
    metadata = PluginMetadata(
        "safe-agents",
        "1.0",
        extension_points=frozenset({AGENT_EXTENSION_POINT}),
    )
    plugin = _Plugin()
    plugin.metadata = metadata
    router = AgentRouter()
    agent = _Agent("architect", {"answer": "ok"})
    router.register(agent)
    adapter = PluginAgentInvocationAdapter(router, role="architect")
    host = PluginHost(extensions={AGENT_EXTENSION_POINT: adapter})

    host.register(plugin)
    host.initialize("safe-agents", _Context(extensions={AGENT_EXTENSION_POINT: adapter}))
    assert plugin.calls == ["initialize"]
    assert adapter.role == "architect"


def test_plugin_agent_adapter_isolates_task_and_result_boundaries():
    router = AgentRouter()
    agent = _Agent("architect", {"nested": {"value": 1}})
    router.register(agent)
    adapter = PluginAgentInvocationAdapter(router, role="architect")
    task = Task("TASK-AGENT-001", "title", "description", "developer", context={"original": True})

    result = adapter.invoke(task)

    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert result.agent == "architect"
    assert result.task_id == task.id
    assert "mutated_by_agent" not in task.context

    result.data["nested"]["value"] = 99
    assert agent.result_data["nested"]["value"] == 1


def test_plugin_agent_adapter_does_not_expose_router_or_agent_internals():
    router = AgentRouter()
    router.register(_Agent("architect"))
    adapter = PluginAgentInvocationAdapter(router, role="architect")

    assert not hasattr(adapter, "router")
    assert not hasattr(adapter, "agent")
    assert not hasattr(adapter, "llm")
    assert adapter.role == "architect"


def test_plugin_agent_adapter_routes_developer_pool_by_task_id():
    router = AgentRouter()
    agents = [_Agent("developer"), _Agent("developer")]
    router.register_developer_pool(agents)
    adapter = PluginAgentInvocationAdapter(router, role="developer")
    task = Task("TASK-AGENT-POOL-001", "title", "description", "developer")

    result = adapter.invoke(task)

    selected = router.get_developer_for_task(task.id)
    assert result.agent == "developer"
    assert selected.received_tasks
    assert selected.received_tasks[-1].id == task.id


def test_workflow_extension_rejects_raw_workflow():
    metadata = PluginMetadata(
        "raw-workflow",
        "1.0",
        extension_points=frozenset({WORKFLOW_EXTENSION_POINT}),
    )
    plugin = _Plugin()
    plugin.metadata = metadata
    workflow = TaskWorkflow.__new__(TaskWorkflow)

    with pytest.raises(PluginError, match="workflow extension must be a PluginWorkflowInvocationAdapter"):
        PluginHost(extensions={WORKFLOW_EXTENSION_POINT: workflow}).register(plugin)


def test_workflow_extension_requires_canonical_invocation_adapter():
    metadata = PluginMetadata(
        "safe-workflow",
        "1.0",
        extension_points=frozenset({WORKFLOW_EXTENSION_POINT}),
    )
    plugin = _Plugin()
    plugin.metadata = metadata
    workflow = TaskWorkflow.__new__(TaskWorkflow)
    adapter = PluginWorkflowInvocationAdapter(workflow)
    host = PluginHost(extensions={WORKFLOW_EXTENSION_POINT: adapter})

    host.register(plugin)
    host.initialize("safe-workflow", _Context(extensions={WORKFLOW_EXTENSION_POINT: adapter}))
    assert plugin.calls == ["initialize"]


def test_plugin_workflow_adapter_returns_detached_task_snapshot():
    workflow = TaskWorkflow.__new__(TaskWorkflow)
    live_task = Task(
        "TASK-WORKFLOW-001",
        "title",
        "description",
        "developer",
        status="completed",
        result={"nested": {"value": 1}},
    )

    def execute(task_id: str):
        assert task_id == live_task.id
        return live_task

    workflow.execute = execute
    adapter = PluginWorkflowInvocationAdapter(workflow)

    snapshot = adapter.execute(task_id=live_task.id)

    assert snapshot["id"] == live_task.id
    assert snapshot["status"] == "completed"
    snapshot["result"]["nested"]["value"] = 99
    assert live_task.result["nested"]["value"] == 1


def test_plugin_workflow_adapter_validates_task_id_and_return_contract():
    workflow = TaskWorkflow.__new__(TaskWorkflow)
    adapter = PluginWorkflowInvocationAdapter(workflow)

    with pytest.raises(ValueError):
        adapter.execute(task_id="   ")

    workflow.execute = lambda task_id: {"id": task_id}
    with pytest.raises(TypeError, match="host Workflow must return Task"):
        adapter.execute(task_id="TASK-WORKFLOW-002")


def test_plugin_workflow_adapter_does_not_expose_workflow_internals():
    workflow = TaskWorkflow.__new__(TaskWorkflow)
    adapter = PluginWorkflowInvocationAdapter(workflow)

    assert not hasattr(adapter, "workflow")
    assert not hasattr(adapter, "task_manager")
    assert not hasattr(adapter, "agent_router")
