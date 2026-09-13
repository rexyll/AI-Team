from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from runtime.delivery_manifest import write_delivery_manifest
from runtime.packaging import create_delivery_package, verify_package


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_package_bundles_all_deliverables_and_verifies(tmp_path: Path):
    root = tmp_path / "e2e_delivery"
    _write(root / "todo.py", "print('todo')")
    _write(root / "docs" / "user_manual.md", "# 手册")
    _write(root / "__pycache__" / "junk.pyc", "junk")  # excluded

    package = create_delivery_package(root, project="todo")

    archive = Path(package["archive"])
    assert archive.name == "e2e_delivery-delivery.zip"
    assert package["files"] == 2  # junk excluded, docs included
    assert package["checksum"] == hashlib.sha256(archive.read_bytes()).hexdigest()

    with zipfile.ZipFile(archive) as bundle:
        assert sorted(bundle.namelist()) == ["docs/user_manual.md", "todo.py"]


def test_package_verification_detects_tampering(tmp_path: Path):
    root = tmp_path / "e2e_delivery"
    _write(root / "todo.py", "print('todo')")
    package = create_delivery_package(root)
    archive = Path(package["archive"])

    entries = [
        {"path": "todo.py", "size": 12, "checksum": "0" * 64},
    ]
    verification = verify_package(archive, entries)

    assert verification["ok"] is False
    assert any("size mismatch" in problem for problem in verification["problems"])


def test_package_fails_closed_on_missing_root(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        create_delivery_package(tmp_path / "missing")


def test_package_fails_closed_when_nothing_to_deliver(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _write(tmp_path / "elsewhere" / "x.txt", "x")

    with pytest.raises(ValueError, match="no deliverable files"):
        create_delivery_package(empty)


def test_package_survives_round_trip_with_manifest(tmp_path: Path):
    root = tmp_path / "e2e_delivery"
    _write(root / "todo.py", "print('todo')")
    manifest = write_delivery_manifest(root, project="todo")

    package = create_delivery_package(root, project="todo")

    import zipfile

    with zipfile.ZipFile(package["archive"]) as bundle:
        assert manifest.name in bundle.namelist()
        assert bundle.read("todo.py") == b"print('todo')"
