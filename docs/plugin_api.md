# Plugin API

AI-Team exposes a small, host-controlled plugin contract for optional extensions.

## Contract

Plugins implement the `Plugin` protocol and provide immutable `PluginMetadata`:

- `name`: unique plugin identifier within a host
- `version`: plugin version
- `api_version`: currently `1.0`
- `capabilities`: explicitly requested capability names

A plugin provides two lifecycle methods:

- `initialize(context)` — called once after registration and capability checks
- `shutdown()` — called when an initialized plugin is stopped

Use `PluginHost` as the lifecycle boundary. Do not call plugin lifecycle methods directly from application code.

## Capability security

Capability declarations are requests, not grants. A plugin must pass both checks:

1. `PluginHost(allowed_capabilities=...)` allows every declared capability.
2. The runtime `PluginContext` reports every declared capability as granted.

A plugin with an undelegated capability is rejected during registration. A plugin whose runtime context lacks a declared capability is rejected during initialization.

The plugin API does not expose the internal tool registry, workspace object, network client, secrets, or agent internals. Extensions should receive only the narrow host-owned APIs they actually need.

## Example

```python
from runtime.plugin_api import PluginHost, PluginMetadata

class MetricsPlugin:
    metadata = PluginMetadata(
        name="metrics-exporter",
        version="1.0.0",
        capabilities=frozenset({"observe"}),
    )

    def initialize(self, context):
        # Use only APIs intentionally exposed by the host context.
        pass

    def shutdown(self):
        pass

host = PluginHost(allowed_capabilities=frozenset({"observe"}))
host.register(MetricsPlugin())
host.initialize("metrics-exporter", context)
```

## Lifecycle rules

Registration rejects duplicate names. Initialization is guarded against repeated calls. Shutdown is safe to call for a registered but uninitialized plugin and always clears the host's initialized state even if plugin shutdown raises.

## Compatibility

`PLUGIN_API_VERSION` is the compatibility boundary. Plugins declaring an unsupported API version are rejected rather than silently adapted. Changes that alter the `Plugin`, `PluginContext`, or metadata contract should introduce a new API version and corresponding regression coverage.
