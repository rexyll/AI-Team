from __future__ import annotations

import runpy


def test_mcp_bridge_module_entrypoint_delegates_to_server_main(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_main() -> None:
        calls.append(True)

    monkeypatch.setattr("mcp_bridge.server.main", fake_main)
    runpy.run_module("mcp_bridge", run_name="__main__")

    assert calls == [True]
