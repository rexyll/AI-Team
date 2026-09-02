from __future__ import annotations

import sys
import types

import pytest

from web_host_bridge.config import MCPBridgeConfig
from web_host_bridge.observability import MCPOperationTracker
from web_host_bridge.server import create_server


class _FakeServer:
    def __init__(self, *args, **kwargs):
        self.tools = {}

    def tool(self, *, name, **kwargs):
        def decorator(func):
            self.tools[name] = func
            return func
        return decorator

    def run(self):
        return None


class _FakeToolAnnotations:
    def __init__(self, **kwargs):
        self.values = kwargs


def _install_fake_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    mcp = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    types_module = types.ModuleType("mcp.types")
    server_module.MCPServer = _FakeServer
    types_module.ToolAnnotations = _FakeToolAnnotations
    mcp.server = server_module
    mcp.types = types_module
    monkeypatch.setitem(sys.modules, "mcp", mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.types", types_module)


def test_server_tracks_successful_operation(monkeypatch, tmp_path) -> None:
    _install_fake_mcp(monkeypatch)
    tracker = MCPOperationTracker()
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path), operation_tracker=tracker)

    result = server.tools["bridge_health"]()

    assert result["status"] == "ok"
    history = tracker.history()
    assert len(history) == 1
    record = history[0]
    assert record["capability"] == "bridge_health"
    assert record["policy_profile"] == "developer"
    assert record["policy_allowed"] is True
    assert record["outcome"] == "success"
    assert record["request_id"]
    assert record["operation_id"]
    assert record["finished_at"]
    assert record["duration_ms"] is not None


def test_server_normalizes_failed_operation_without_changing_exception(monkeypatch, tmp_path) -> None:
    _install_fake_mcp(monkeypatch)
    tracker = MCPOperationTracker()
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path), operation_tracker=tracker)

    with pytest.raises((FileNotFoundError, ValueError, RuntimeError)):
        server.tools["workspace_read_file"]("missing.txt")

    record = tracker.history()[0]
    assert record["capability"] == "workspace_read_file"
    assert record["outcome"] == "error"
    assert record["error_type"] in {"bridge_error", "not_found", "invalid_request"}
    assert record["metadata"]["error_type"]
