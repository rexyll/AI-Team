from __future__ import annotations
import os
import stat
from pathlib import Path
import pytest

from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_state import LocalDockerRouterStateStore

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Router state permissions require POSIX")

def scope(project="alpha", environment="test"):
    return TrafficRouterScope("docker-local", project, environment)

def bindings():
    return (TrafficPortBinding(8080, 80), TrafficPortBinding(8443, 443))

def test_persist_creates_private_scope_directory_and_files(tmp_path):
    result = LocalDockerRouterStateStore(tmp_path / "router-state").persist(scope(), bindings())
    assert result.status == "persisted"
    record = result.record
    assert stat.S_IMODE(os.stat(record.directory).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(record.config_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(record.active_slot_map_path).st_mode) == 0o600
    assert Path(record.config_path).read_text(encoding="utf-8").startswith("global\n")
    assert Path(record.active_slot_map_path).read_text(encoding="utf-8") == "active none\n"
    assert len(record.config_sha256) == len(record.active_slot_map_sha256) == 64

def test_scope_paths_are_deterministic_and_isolated(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    a = store.persist(scope(), bindings()).record
    b = store.persist(scope(), bindings()).record
    c = store.persist(scope(project="beta"), bindings()).record
    assert a.directory == b.directory and a.directory != c.directory
    assert "alpha" not in a.directory and "test" not in a.directory

def test_only_allowlisted_active_slot_values_are_persisted(tmp_path):
    result = LocalDockerRouterStateStore(tmp_path / "router-state").persist(scope(), bindings(), active_slot="slot_b")
    assert result.status == "persisted"
    assert Path(result.record.active_slot_map_path).read_text(encoding="utf-8") == "active slot_b\n"

def test_invalid_active_slot_fails_without_trusted_record(tmp_path):
    result = LocalDockerRouterStateStore(tmp_path / "router-state").persist(scope(), bindings(), active_slot="other")
    assert result.status == "failed" and result.record is None

def test_duplicate_ports_fail_before_state_directory_is_created(tmp_path):
    result = LocalDockerRouterStateStore(tmp_path / "router-state").persist(scope(), (TrafficPortBinding(8080, 80), TrafficPortBinding(8080, 81)))
    assert result.status == "failed" and result.record is None
    assert not (tmp_path / "router-state").exists()

def test_symlink_root_is_rejected_without_writing_through_it(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    link = tmp_path / "linked"
    link.symlink_to(actual, target_is_directory=True)
    result = LocalDockerRouterStateStore(link).persist(scope(), bindings())
    assert result.status == "failed" and result.record is None
    assert list(actual.iterdir()) == []

def test_symlink_state_file_is_rejected_without_touching_target(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    first = store.persist(scope(), bindings())
    target = tmp_path / "outside"
    target.write_text("do-not-touch", encoding="utf-8")
    os.chmod(target, 0o600)
    os.unlink(first.record.config_path)
    os.symlink(target, first.record.config_path)
    result = store.persist(scope(), bindings())
    assert result.status == "failed" and target.read_text(encoding="utf-8") == "do-not-touch"

def test_hardlinked_state_file_is_rejected(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    first = store.persist(scope(), bindings())
    linked = tmp_path / "outside-hardlink"
    os.link(first.record.config_path, linked)
    result = store.persist(scope(), bindings())
    assert result.status == "failed" and linked.read_bytes().startswith(b"global\n")

def test_existing_loose_directory_permissions_are_tightened(tmp_path):
    root = tmp_path / "router-state"
    root.mkdir(mode=0o755)
    os.chmod(root, 0o755)
    result = LocalDockerRouterStateStore(root).persist(scope(), bindings())
    assert result.status == "persisted" and stat.S_IMODE(os.stat(root).st_mode) == 0o700

def test_atomic_replacement_leaves_no_temp_files(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    first = store.persist(scope(), bindings())
    second = store.persist(scope(), bindings(), active_slot="slot_a")
    assert second.status == "persisted"
    assert Path(second.record.active_slot_map_path).read_text(encoding="utf-8") == "active slot_a\n"
    assert not list(Path(second.record.directory).glob("*.tmp"))
    assert first.record.directory == second.record.directory
