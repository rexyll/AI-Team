from __future__ import annotations


class MCPBridgeError(RuntimeError):
    """Base exception for Local MCP Bridge failures."""

    error_category = "bridge_error"


class MCPBridgeConfigurationError(MCPBridgeError):
    """Raised when the bridge cannot start with a safe configuration."""

    error_category = "configuration_error"


class MCPBridgePolicyError(MCPBridgeError):
    """Raised when the configured MCP policy does not allow an operation."""

    error_category = "policy_denied"
