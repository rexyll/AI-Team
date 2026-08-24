"""Console logging robustness contracts.

Real provider runs print tool payloads that may contain characters
outside the legacy console codepage (e.g. GBK on Chinese Windows). A
single unencodable character used to kill the whole running task via
UnicodeEncodeError inside the agent's own progress logging. These
contracts pin the log-safe stream guard.
"""

from __future__ import annotations

from pathlib import Path

import main


ROOT = Path(__file__).resolve().parents[1]


class _FakeStream:
    def __init__(self) -> None:
        self.reconfigure_kwargs: dict | None = None

    def reconfigure(self, **kwargs):
        self.reconfigure_kwargs = dict(kwargs)


class _PlainStream:
    """A stream without ``reconfigure`` (e.g. pytest capture objects)."""


def test_main_source_wires_log_safe_stream_guard() -> None:
    content = (ROOT / "main.py").read_text(encoding="utf-8-sig")

    assert "_ensure_log_safe_streams" in content
    assert 'errors="replace"' in content
    # The guard must be invoked from the CLI entry point itself.
    assert "_ensure_log_safe_streams()" in content


def test_guard_replaces_unencodable_characters_on_both_streams(
    monkeypatch,
) -> None:
    out, err = _FakeStream(), _FakeStream()
    monkeypatch.setattr(main.sys, "stdout", out)
    monkeypatch.setattr(main.sys, "stderr", err)

    main._ensure_log_safe_streams()

    assert out.reconfigure_kwargs == {"errors": "replace"}
    assert err.reconfigure_kwargs == {"errors": "replace"}


def test_guard_tolerates_streams_without_reconfigure(monkeypatch) -> None:
    monkeypatch.setattr(main.sys, "stdout", _PlainStream())
    monkeypatch.setattr(main.sys, "stderr", _PlainStream())

    # Must not raise for capture-style streams lacking ``reconfigure``.
    main._ensure_log_safe_streams()
