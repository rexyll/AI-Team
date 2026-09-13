from __future__ import annotations

import hashlib
from pathlib import Path

from runtime.delivery_manifest import (
    collect_deliverables,
    render_delivery_manifest,
    write_delivery_manifest,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_collect_lists_deliverables_with_checksums(tmp_path: Path):
    _write(tmp_path / "app.py", "print('ok')")
    _write(tmp_path / "docs" / "user_manual.md", "# 手册")

    entries = collect_deliverables(tmp_path)

    assert [entry["path"] for entry in entries] == ["app.py", "docs/user_manual.md"]
    assert entries[0]["checksum"] == hashlib.sha256(b"print('ok')").hexdigest()
    assert entries[0]["size"] == len(b"print('ok')")


def test_collect_excludes_runtime_artifacts(tmp_path: Path):
    _write(tmp_path / "app.py", "print('ok')")
    _write(tmp_path / "__pycache__" / "app.cpython.pyc", "junk")
    _write(tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed", "{}")
    _write(tmp_path / ".venv" / "pyvenv.cfg", "config")

    entries = collect_deliverables(tmp_path)

    assert [entry["path"] for entry in entries] == ["app.py"]


def test_manifest_renders_table_and_counts(tmp_path: Path):
    _write(tmp_path / "app.py", "print('ok')")

    manifest_path = write_delivery_manifest(tmp_path, project="wordcount")
    manifest = manifest_path.read_text(encoding="utf-8")

    assert manifest_path.name == "DELIVERY_MANIFEST.md"
    assert "| app.py |" in manifest
    assert hashlib.sha256(b"print('ok')").hexdigest() in manifest
    # The manifest is written after collection, so it does not list itself.
    assert "共 1 个文件" in manifest


def test_render_without_project_and_empty_root(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()

    assert collect_deliverables(empty) == []
    manifest = render_delivery_manifest([], project=None)
    assert "共 0 个文件" in manifest
