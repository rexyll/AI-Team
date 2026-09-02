from __future__ import annotations


class MCPBridgeError(RuntimeError):
    """Base exception for Local MCP Bridge failures."""


class MCPBridgeConfigurationError(MCPBridgeError):
    """Raised when the bridge cannot start with a safe configuration."""


class MCPBridgePolicyError(MCPBridgeError):
    """Raised when the configured MCP policy does not allow an operation."""
