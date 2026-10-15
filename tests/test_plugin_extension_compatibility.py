import pytest

from agents.base import BaseAgent
from runtime.agent_config import AgentConfig
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.base import BaseLLM
from runtime.plugin_agent_adapter import PluginAgentInvocationAdapter
from runtime.plugin_api import (
    AGENT_EXTENSION_POINT,
    PluginError,
    PluginHost,
    PluginMetadata,
    TOOL_EXTENSION_POINT,
    WORKFLOW_EXTENSION_POINT,
)
from runtime.plugin_tool_adapter import PluginToolInvocationAdapter
from runtime.plugin_workflow_adapter import PluginWorkflowInvocationAdapter
from runtime.tool_invocation_service import ToolInvocationService
from runtime.task import Task
from runtime.workflow import TaskWorkflow


class _NoOpLLM(BaseLLM):
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        return "ok"


class _Agent(BaseAgent):
    def __init__(self, role: str):
        super().__init__(AgentConfig(role=role, model=""), llm=_NoOpLLM())
        self._role = role

    @property
    def role(self):
        return self._role

    def run(self, task: Task) -> AgentResult:
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            data={},
        )


class _Context:
    def __init__(self, extensions):
        self.extensions = dict(extensions)

    def has_capability(self, capability):
        return capability == "observe"

    def get_extension(self, extension_point):
        return self.extensions.get(extension_point)


class _Plugin:
    metadata = PluginMetadata(
        "compatibility",
        "1.0",
        capabilities=frozenset({"observe"}),
        extension_points=frozenset(
            {TOOL_EXTENSION_POINT, AGENT_EXTENSION_POINT, WORKFLOW_EXTENSION_POINT}
        ),
    )

    def __init__(self):
        self.context = None

    def initialize(self, context):
        self.context = context

    def shutdown(self):
        pass


def _canonical_extensions():
    router = AgentRouter()
    router.register(_Agent("architect"))
    return {
        TOOL_EXTENSION_POINT: PluginToolInvocationAdapter(ToolInvocationService(), role="developer"),
        AGENT_EXTENSION_POINT: PluginAgentInvocationAdapter(router, role="architect"),
        WORKFLOW_EXTENSION_POINT: PluginWorkflowInvocationAdapter(TaskWorkflow.__new__(TaskWorkflow)),
    }


def test_all_reserved_extension_points_can_be_registered_and_context_bound():
    extensions = _canonical_extensions()
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}), extensions=extensions)

    host.register(plugin)
    host.initialize("compatibility", _Context(extensions))

    for point, extension in extensions.items():
        assert plugin.context.get_extension(point) is extension


def test_reserved_extensions_reject_non_canonical_values_independently():
    cases = (
        (TOOL_EXTENSION_POINT, ToolInvocationService(), "PluginToolInvocationAdapter"),
        (AGENT_EXTENSION_POINT, AgentRouter(), "PluginAgentInvocationAdapter"),
        (WORKFLOW_EXTENSION_POINT, TaskWorkflow.__new__(TaskWorkflow), "PluginWorkflowInvocationAdapter"),
    )
    for point, bad_value, expected in cases:
        plugin = _Plugin()
        plugin.metadata = PluginMetadata(f"bad-{point}", "1.0", extension_points=frozenset({point}))
        with pytest.raises(PluginError, match=expected):
            PluginHost(extensions={point: bad_value}).register(plugin)


def test_context_cannot_substitute_host_approved_reserved_extension():
    extensions = _canonical_extensions()
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}), extensions=extensions)
    host.register(plugin)
    substituted = dict(extensions)
    substituted[AGENT_EXTENSION_POINT] = object()

    with pytest.raises(PermissionError, match="extension point not provided by host context"):
        host.initialize("compatibility", _Context(substituted))
