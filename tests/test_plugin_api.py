import pytest

from runtime.plugin_api import PLUGIN_API_VERSION, PluginHost, PluginMetadata


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
    assert metadata.capabilities == frozenset({"observe"})


def test_plugin_registration_rejects_undelegated_capability():
    plugin = _Plugin()
    with pytest.raises(PermissionError, match="denied capabilities"):
        PluginHost().register(plugin)


def test_plugin_lifecycle_requires_host_and_context_capability():
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}))
    host.register(plugin)

    with pytest.raises(PermissionError, match="not granted"):
        host.initialize("demo", _Context())

    host.initialize("demo", _Context("observe"))
    host.shutdown("demo")
    assert plugin.calls == ["initialize", "shutdown"]


def test_plugin_initialize_is_idempotency_guarded():
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}))
    host.register(plugin)
    host.initialize("demo", _Context("observe"))

    with pytest.raises(Exception, match="already initialized"):
        host.initialize("demo", _Context("observe"))


def test_plugin_metadata_is_listed_without_exposing_plugin_objects():
    plugin = _Plugin()
    host = PluginHost(allowed_capabilities=frozenset({"observe"}))
    host.register(plugin)
    listed = host.list_plugins()
    assert listed == (plugin.metadata,)
