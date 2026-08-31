import pytest

from runtime.plugin_api import (
    PLUGIN_API_VERSION,
    PluginHost,
    PluginLifecycleError,
    PluginMetadata,
)


class _Context:
    def __init__(self, *capabilities):
        self.capabilities = set(capabilities)

    def has_capability(self, capability):
        return capability in self.capabilities


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
