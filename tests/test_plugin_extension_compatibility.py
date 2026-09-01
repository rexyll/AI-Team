import pytest

from runtime.agent_router import AgentRouter
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
from runtime.workflow import TaskWorkflow


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
    return {
        TOOL_EXTENSION_POINT: PluginToolInvocationAdapter(ToolInvocationService(), role="developer"),
        AGENT_EXTENSION_POINT: PluginAgentInvocationAdapter(AgentRouter(), role="architect"),
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
    host = PluginHost(extensions=extensions)
    host.register(plugin)
    substituted = dict(extensions)
    substituted[AGENT_EXTENSION_POINT] = object()

    with pytest.raises(PermissionError, match="extension point not provided by host context"):
        host.initialize("compatibility", _Context(substituted))
