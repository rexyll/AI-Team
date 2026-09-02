from __future__ import annotations

import runpy


def test_web_host_bridge_module_entrypoint_delegates_to_server_main(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_main() -> None:
        calls.append(True)

    monkeypatch.setattr("web_host_bridge.server.main", fake_main)
    runpy.run_module("web_host_bridge", run_name="__main__")

    assert calls == [True]
