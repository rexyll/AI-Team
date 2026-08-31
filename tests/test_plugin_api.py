import pytest

from runtime.plugin_api import (
    PLUGIN_API_VERSION,
    PluginError,
    PluginHost,
    PluginLifecycleError,
    PluginMetadata,
    TOOL_EXTENSION_POINT,
)
from runtime.plugin_tool_adapter import PluginToolInvocationAdapter
from runtime.tool_invocation_service import ToolInvocationService
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
        tool_name="read_file",
        arguments={"path": "README.md"},
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_PERMISSION_DENIED"
    assert service.audit.count() == 1
    record = service.audit.records()[0]
    assert record.agent_role == "reviewer"
    assert record.tool_name == "read_file"


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
