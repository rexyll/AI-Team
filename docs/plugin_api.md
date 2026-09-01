# Plugin API

AI-Team exposes a small, host-controlled plugin contract for optional extensions.

## Contract

Plugins implement the `Plugin` protocol and provide immutable `PluginMetadata`:

- `name`: unique plugin identifier within a host
- `version`: plugin version
- `api_version`: currently `1.0`
- `capabilities`: explicitly requested capability names
- `extension_points`: named host services the plugin expects to consume

A plugin provides two lifecycle methods:

- `initialize(context)` — called once after registration and capability/extension checks
- `shutdown()` — called when an initialized plugin is stopped

Use `PluginHost` as the lifecycle boundary. Do not call plugin lifecycle methods directly from application code.

## Extension points

Extension points are explicit, host-owned dependencies. A plugin may name an extension point in metadata, but that does not make the service available automatically.

The host must register the extension object with `PluginHost(extensions={...})`, and the runtime context must return the same host-approved object from `get_extension(name)`. This keeps extension access explicit and prevents a plugin from inventing or discovering arbitrary runtime services.

For example, a host may expose a narrow `dashboard` adapter rather than the internal dashboard implementation, or an `observe` adapter rather than the complete metrics registry.

### Tool extension boundary

The reserved `tools` extension point is stricter than a generic extension point. Its value must be a `PluginToolInvocationAdapter` constructed by the host around the canonical `ToolInvocationService`.

The adapter exposes only:

```python
invoke(
    task_id=...,
    execution_id=...,
    tool_name=...,
    arguments=...,
)
```

The authorization role is fixed when the host constructs the adapter and is never supplied by the plugin. Tool calls therefore continue through the canonical runtime capability, permission, argument-validation, audit, and tracing boundaries.

A raw `ToolRegistry`, raw tool callable, workspace object, or `ToolInvocationService` must not be exposed as the plugin `tools` extension. `PluginHost` rejects a non-adapter value for that reserved extension point during registration.

### Agent extension boundary

The reserved `agents` extension point is host-owned. Its value must be a `PluginAgentInvocationAdapter` constructed around the host `AgentRouter`.

The adapter exposes only:

```python
invoke(task) -> AgentResult
```

The Agent role is fixed when the host constructs the adapter and cannot be overridden by the plugin. Singleton roles are resolved through the existing router, while the `developer` role continues to use the router's deterministic Developer-pool selection by task ID.

The adapter executes against an isolated copy of the `Task` and returns an isolated copy of the canonical `AgentResult`. This prevents plugins from mutating host runtime state through object aliases. The raw router, Agent instance, LLM, tool-loop state, and mutable runtime Task are not exposed through the adapter.

A raw `AgentRouter`, raw `BaseAgent`, LLM instance, workspace object, or internal Agent state must not be exposed as the plugin `agents` extension. `PluginHost` rejects a non-adapter value for that reserved extension point during registration.

## Capability security

Capability declarations are requests, not grants. A plugin must pass both checks:

1. `PluginHost(allowed_capabilities=...)` allows every declared capability.
2. The runtime `PluginContext` reports every declared capability as granted.

Extension points have an additional two-sided check:

1. The host must provide the named extension point.
2. The runtime context must provide the exact host-approved object for that name.

Reserved `tools` and `agents` extension points add a third check: the value must be the corresponding host-owned adapter rather than a raw internal runtime object.

A plugin with an undelegated capability is rejected during registration. A plugin whose runtime context lacks a declared capability or extension point is rejected during initialization.

The plugin API does not expose the internal tool registry, workspace object, network client, secrets, or agent internals. Extensions should receive only the narrow host-owned APIs they actually need.

## Example

```python
from runtime.plugin_api import PluginHost, PluginMetadata

class MetricsPlugin:
    metadata = PluginMetadata(
        name="metrics-exporter",
        version="1.0.0",
        capabilities=frozenset({"observe"}),
        extension_points=frozenset({"metrics"}),
    )

    def initialize(self, context):
        metrics = context.get_extension("metrics")
        # Use only the narrow host-approved metrics adapter.

    def shutdown(self):
        pass

metrics_adapter = object()
host = PluginHost(
    allowed_capabilities=frozenset({"observe"}),
    extensions={"metrics": metrics_adapter},
)
host.register(MetricsPlugin())
host.initialize("metrics-exporter", context)
```

## Lifecycle rules

Registration rejects duplicate names, denied capabilities, unavailable extension points, raw values for reserved `tools` / `agents` extension points, and incorrect host-owned adapter types. Initialization is guarded against repeated calls and verifies runtime capability/extension grants before invoking the plugin. Shutdown is safe to call for a registered but uninitialized plugin and always clears the host's initialized state even if plugin shutdown raises.

## Compatibility

`PLUGIN_API_VERSION` is the compatibility boundary. Plugins declaring an unsupported API version are rejected rather than silently adapted. Changes that alter the `Plugin`, `PluginContext`, metadata, lifecycle, or extension-point contract should introduce a new API version and corresponding regression coverage.
