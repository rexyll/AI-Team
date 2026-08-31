"""Stable, capability-scoped plugin API for AI-Team extensions.

Plugins are deliberately passive: declaring a capability does not grant access
by itself. Hosts decide which capabilities are allowed and provide only the
extension points explicitly requested by the plugin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


PLUGIN_API_VERSION = "1.0"


class PluginError(RuntimeError):
    """Base error for plugin contract violations."""


class PluginLifecycleError(PluginError):
    """Raised when plugin lifecycle operations are invalid."""


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str
    api_version: str = PLUGIN_API_VERSION
    capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("plugin name must be non-empty")
        if not self.version.strip():
            raise ValueError("plugin version must be non-empty")
        if self.api_version != PLUGIN_API_VERSION:
            raise ValueError(f"unsupported plugin API version: {self.api_version}")
        if any(not capability.strip() for capability in self.capabilities):
            raise ValueError("plugin capabilities must be non-empty strings")


class PluginContext(Protocol):
    """Host-owned context; implementations must expose only approved APIs."""

    def has_capability(self, capability: str) -> bool: ...


class Plugin(Protocol):
    metadata: PluginMetadata

    def initialize(self, context: PluginContext) -> None: ...

    def shutdown(self) -> None: ...


class PluginHost:
    """Lifecycle manager enforcing declared/allowed capability boundaries."""

    def __init__(self, *, allowed_capabilities: frozenset[str] = frozenset()) -> None:
        self._allowed_capabilities = frozenset(allowed_capabilities)
        self._plugins: dict[str, Plugin] = {}
        self._initialized: set[str] = set()

    @property
    def allowed_capabilities(self) -> frozenset[str]:
        return self._allowed_capabilities

    def register(self, plugin: Plugin) -> None:
        metadata = plugin.metadata
        if not isinstance(metadata, PluginMetadata):
            raise TypeError("plugin.metadata must be PluginMetadata")
        if metadata.name in self._plugins:
            raise PluginError(f"plugin already registered: {metadata.name}")
        denied = metadata.capabilities - self._allowed_capabilities
        if denied:
            raise PermissionError(
                f"plugin '{metadata.name}' requests denied capabilities: "
                + ", ".join(sorted(denied))
            )
        self._plugins[metadata.name] = plugin

    def initialize(self, name: str, context: PluginContext) -> None:
        if name not in self._plugins:
            raise KeyError(f"unknown plugin: {name}")
        if name in self._initialized:
            raise PluginLifecycleError(f"plugin already initialized: {name}")
        plugin = self._plugins[name]
        for capability in plugin.metadata.capabilities:
            if not context.has_capability(capability):
                raise PermissionError(
                    f"plugin '{name}' capability not granted by context: {capability}"
                )
        plugin.initialize(context)
        self._initialized.add(name)

    def shutdown(self, name: str) -> None:
        if name not in self._plugins:
            raise KeyError(f"unknown plugin: {name}")
        if name not in self._initialized:
            return
        try:
            self._plugins[name].shutdown()
        finally:
            self._initialized.discard(name)

    def list_plugins(self) -> tuple[PluginMetadata, ...]:
        return tuple(plugin.metadata for plugin in self._plugins.values())
