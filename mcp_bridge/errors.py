from __future__ import annotations


class MCPBridgeError(RuntimeError):
    """Base exception for Local MCP Bridge failures."""


class MCPBridgeConfigurationError(MCPBridgeError):
    """Raised when the bridge cannot start with a safe configuration."""
