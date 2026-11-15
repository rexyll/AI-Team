from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from runtime.deployment import stage_deliverable_copy


def test_stage_copy_includes_static_assets_but_excludes_mutable_environments(
    tmp_path: Path,
) -> None:
    root = tmp_path / "deliverable"
    (root / "tests").mkdir(parents=True)
    (root / "dist").mkdir()
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / "node_modules" / "package").mkdir(parents=True)
    (root / ".ai-team-cache").mkdir()
    (root / ".git").mkdir()

    (root / "tests" / "test_web.py").write_text(
        "from pathlib import Path\n"
        "def test_built_asset():\n"
        "    assert Path('dist/index.html').read_text() == 'built'\n",
        encoding="utf-8",
    )
    (root / "dist" / "index.html").write_text("built", encoding="utf-8")
    (root / "package.json").write_text('{"scripts":{"test":"node --test"}}\n', encoding="utf-8")
    (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"environment")
    (root / "node_modules" / "package" / "index.js").write_text(
        "module.exports = true;\n", encoding="utf-8"
    )
    (root / ".ai-team-cache" / "cache.bin").write_bytes(b"cache")
    (root / ".git" / "config").write_text("private", encoding="utf-8")

    staged = stage_deliverable_copy(root)
    try:
        assert (staged / "tests" / "test_web.py").is_file()
        assert (staged / "dist" / "index.html").read_text(encoding="utf-8") == "built"
        assert (staged / "package.json").is_file()
        assert not (staged / ".venv").exists()
        assert not (staged / "node_modules").exists()
        assert not (staged / ".ai-team-cache").exists()
        assert not (staged / ".git").exists()
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def test_stage_copy_never_follows_file_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("must not enter staging", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable on this runner: {type(exc).__name__}")

    staged = stage_deliverable_copy(root)
    try:
        assert not (staged / "linked.txt").exists()
    finally:
        shutil.rmtree(staged, ignore_errors=True)
