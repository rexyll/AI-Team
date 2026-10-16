import hashlib

import pytest

from runtime.developer_workspace import (
    DeveloperWorkspaceManager,
    WorkspaceLease,
    WorkspaceMergeConflict,
)


def manager(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "existing.txt").write_text("base", encoding="utf-8")
    return DeveloperWorkspaceManager(root), root


def test_issue_copies_main_tree_and_records_base_hashes(tmp_path):
    mgr, root = manager(tmp_path)
    lease = mgr.issue("TASK-001")
    assert (lease.root / "existing.txt").read_text(encoding="utf-8") == "base"
    assert lease.base_hashes == {"existing.txt": hashlib.sha256(b"base").hexdigest()}


def test_merge_applies_changed_and_added_files(tmp_path):
    mgr, root = manager(tmp_path)
    lease = mgr.issue("TASK-001")
    (lease.root / "existing.txt").write_text("revised", encoding="utf-8")
    (lease.root / "new.py").write_text("print(1)", encoding="utf-8")
    report = mgr.merge(lease)
    assert (root / "existing.txt").read_text(encoding="utf-8") == "revised"
    assert (root / "new.py").read_text(encoding="utf-8") == "print(1)"
    assert report.changed == ("existing.txt",)
    assert report.added == ("new.py",)


def test_merge_detects_concurrent_write_conflict(tmp_path):
    mgr, root = manager(tmp_path)
    lease = mgr.issue("TASK-001")
    (lease.root / "existing.txt").write_text("dev version", encoding="utf-8")
    (root / "existing.txt").write_text("main moved on", encoding="utf-8")
    with pytest.raises(WorkspaceMergeConflict, match="existing.txt"):
        mgr.merge(lease)


def test_merge_applies_deletion_unless_main_changed(tmp_path):
    mgr, root = manager(tmp_path)
    (root / "doomed.txt").write_text("x", encoding="utf-8")
    lease = mgr.issue("TASK-002")
    (lease.root / "doomed.txt").unlink()
    report = mgr.merge(lease)
    assert not (root / "doomed.txt").exists()
    assert report.deleted == ("doomed.txt",)

    (root / "keep.txt").write_text("x", encoding="utf-8")
    lease2 = mgr.issue("TASK-003")
    (lease2.root / "keep.txt").unlink()
    (root / "keep.txt").write_text("changed elsewhere", encoding="utf-8")
    with pytest.raises(WorkspaceMergeConflict, match="keep.txt"):
        mgr.merge(lease2)


def test_discard_removes_lease_directory(tmp_path):
    mgr, _ = manager(tmp_path)
    lease = mgr.issue("TASK-001")
    assert lease.root.exists()
    mgr.discard(lease)
    assert not lease.root.exists()


def test_cache_directories_are_never_copied_or_merged(tmp_path):
    mgr, root = manager(tmp_path)
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "junk.pyc").write_text("x", encoding="utf-8")
    (root / ".pytest_cache").mkdir()
    (root / ".pytest_cache" / "v").mkdir()
    lease = mgr.issue("TASK-001")
    assert not (lease.root / "__pycache__").exists()
    assert not (lease.root / ".pytest_cache").exists()
    (lease.root / ".pytest_cache" / "v").mkdir(parents=True)
    (lease.root / ".pytest_cache" / "v" / "junk").write_text("y", encoding="utf-8")
    report = mgr.merge(lease)
    assert not (root / ".pytest_cache" / "v" / "junk").exists()
    assert report.added == ()


def test_issue_replaces_stale_lease_from_crashed_round(tmp_path):
    mgr, _ = manager(tmp_path)
    lease = mgr.issue("TASK-001")
    stale_marker = lease.root / "stale.txt"
    stale_marker.write_text("half-finished", encoding="utf-8")
    fresh = mgr.issue("TASK-001")
    assert not (fresh.root / "stale.txt").exists()


def test_lease_type_is_enforced(tmp_path):
    mgr, _ = manager(tmp_path)
    with pytest.raises(TypeError):
        mgr.merge(object())
    with pytest.raises(TypeError):
        mgr.discard("lease")
