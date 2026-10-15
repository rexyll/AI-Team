"""Stable, capability-scoped plugin API for AI-Team extensions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from runtime.plugin_agent_adapter import PluginAgentInvocationAdapter
from runtime.plugin_tool_adapter import PluginToolInvocationAdapter
from runtime.plugin_workflow_adapter import PluginWorkflowInvocationAdapter

PLUGIN_API_VERSION = "1.0"
TOOL_EXTENSION_POINT = "tools"
AGENT_EXTENSION_POINT = "agents"
WORKFLOW_EXTENSION_POINT = "workflow"


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
    extension_points: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("plugin name must be non-empty")
        if not self.version.strip():
            raise ValueError("plugin version must be non-empty")
        if self.api_version != PLUGIN_API_VERSION:
            raise ValueError(f"unsupported plugin API version: {self.api_version}")
        if any(not value.strip() for value in self.capabilities):
            raise ValueError("plugin capabilities must be non-empty strings")
        if any(not value.strip() for value in self.extension_points):
            raise ValueError("plugin extension points must be non-empty strings")


class PluginContext(Protocol):
    """Host-owned context; implementations must expose only approved APIs."""

    def has_capability(self, capability: str) -> bool: ...

    def get_extension(self, extension_point: str) -> Any: ...


class Plugin(Protocol):
    metadata: PluginMetadata

    def initialize(self, context: PluginContext) -> None: ...

    def shutdown(self) -> None: ...


class PluginHost:
    """Lifecycle manager enforcing declared/allowed capabilities and extensions."""

    def __init__(
        self,
        *,
        allowed_capabilities: frozenset[str] = frozenset(),
        extensions: dict[str, Any] | None = None,
    ) -> None:
        self._allowed_capabilities = frozenset(allowed_capabilities)
        self._extensions = dict(extensions or {})
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
        missing_extensions = metadata.extension_points - self._extensions.keys()
        if missing_extensions:
            raise PluginError(
                f"plugin '{metadata.name}' requests unavailable extension points: "
                + ", ".join(sorted(missing_extensions))
            )
        tools_extension = self._extensions.get(TOOL_EXTENSION_POINT)
        if TOOL_EXTENSION_POINT in metadata.extension_points and not isinstance(
            tools_extension, PluginToolInvocationAdapter
        ):
            raise PluginError(
                f"plugin '{metadata.name}' tools extension must be a "
                "PluginToolInvocationAdapter"
            )
        agents_extension = self._extensions.get(AGENT_EXTENSION_POINT)
        if AGENT_EXTENSION_POINT in metadata.extension_points and not isinstance(
            agents_extension, PluginAgentInvocationAdapter
        ):
            raise PluginError(
                f"plugin '{metadata.name}' agents extension must be a "
                "PluginAgentInvocationAdapter"
            )
        workflow_extension = self._extensions.get(WORKFLOW_EXTENSION_POINT)
        if WORKFLOW_EXTENSION_POINT in metadata.extension_points and not isinstance(
            workflow_extension, PluginWorkflowInvocationAdapter
        ):
            raise PluginError(
                f"plugin '{metadata.name}' workflow extension must be a "
                "PluginWorkflowInvocationAdapter"
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
        for extension_point in plugin.metadata.extension_points:
            if context.get_extension(extension_point) is not self._extensions[extension_point]:
                raise PermissionError(
                    f"plugin '{name}' extension point not provided by host context: {extension_point}"
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
