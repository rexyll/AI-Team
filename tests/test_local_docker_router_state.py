from __future__ import annotations
import os
import stat
from pathlib import Path
import pytest

from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_state import LocalDockerRouterStateStore
from runtime.haproxy_runtime_readback import parse_show_servers_state

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
    assert stat.S_IMODE(os.stat(record.server_state_path).st_mode) == 0o600
    assert record.server_state_sha256 == __import__("hashlib").sha256(Path(record.server_state_path).read_bytes()).hexdigest()
    assert Path(record.config_path).read_text(encoding="utf-8").startswith("global\n")
    assert Path(record.active_slot_map_path).read_text(encoding="utf-8") == "active none\n"
    assert len(record.config_sha256) == len(record.active_slot_map_sha256) == 64

def test_scope_paths_are_deterministic_and_isolated(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    a = store.persist(scope(), bindings()).record
    b = store.persist(scope(), bindings()).record
    c = store.persist(scope(project="beta"), bindings()).record
    assert a.directory == b.directory and a.directory != c.directory
    assert a.network_name == b.network_name and a.network_name != c.network_name
    assert "alpha" not in a.network_name and "test" not in a.network_name

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


def _server_state_snapshot():
    header = (
        "# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state "
        "srv_uweight srv_iweight srv_time_since_last_change srv_check_status "
        "srv_check_result srv_check_health srv_check_state srv_agent_state "
        "bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl "
        "srv_check_port srv_check_addr srv_agent_addr srv_agent_port"
    )
    rows = []
    for index, host_port in enumerate((8080, 8443), start=1):
        for server_id, server in enumerate(("slot_a", "slot_b"), start=1):
            rows.append(
                f"{index} be_p{host_port} {server_id} {server} 127.0.0.1 0 0 "
                f"0 0 0 6 0 0 6 0 0 0 - 1 - 0 1 127.0.0.1 - 0"
            )
    return "1\n" + header + "\n" + "\n".join(rows) + "\n"


def test_persist_servers_state_atomically_updates_private_restart_snapshot(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    first = store.persist(scope(), bindings())
    assert first.status == "persisted"
    second = store.persist_servers_state(first.record, bindings(), _server_state_snapshot())
    assert second.status == "persisted"
    record = second.record
    assert stat.S_IMODE(os.stat(record.server_state_path).st_mode) == 0o600
    assert record.server_state_sha256 == __import__("hashlib").sha256(Path(record.server_state_path).read_bytes()).hexdigest()
    parsed = parse_show_servers_state(Path(record.server_state_path).read_text(encoding="utf-8"))
    assert {(row.backend, row.server) for row in parsed} == {
        (f"be_p{port}", slot)
        for port in (8080, 8443)
        for slot in ("slot_a", "slot_b")
    }


@pytest.mark.parametrize("content", ["", "1\n# missing rows\n", _server_state_snapshot().replace("be_p8080 2 slot_b", "be_p8080 2 slot_a")])
def test_persist_servers_state_rejects_incomplete_or_duplicate_slot_snapshots(tmp_path, content):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    first = store.persist(scope(), bindings())
    result = store.persist_servers_state(first.record, bindings(), content)
    assert result.status == "failed" and result.record is None


def test_persist_active_slot_map_uses_expected_prior_value_and_returns_new_digest(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    initial = store.persist(scope(), bindings(), active_slot=None)
    assert initial.status == "persisted"
    updated = store.persist_active_slot_map(
        initial.record, expected_active_slot=None, active_slot="slot_b"
    )
    assert updated.status == "persisted"
    assert Path(updated.record.active_slot_map_path).read_text(encoding="utf-8") == "active slot_b\n"
    assert updated.record.active_slot_map_sha256 == __import__("hashlib").sha256(
        Path(updated.record.active_slot_map_path).read_bytes()
    ).hexdigest()
    assert updated.record.config_sha256 == initial.record.config_sha256
    assert updated.record.server_state_sha256 == initial.record.server_state_sha256


def test_persist_active_slot_map_rejects_stale_record_or_prior_selector(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    initial = store.persist(scope(), bindings(), active_slot=None)
    changed = store.persist_active_slot_map(
        initial.record, expected_active_slot=None, active_slot="slot_a"
    )
    assert changed.status == "persisted"
    stale = store.persist_active_slot_map(
        initial.record, expected_active_slot=None, active_slot="slot_b"
    )
    assert stale.status == "failed"
    assert Path(initial.record.active_slot_map_path).read_text(encoding="utf-8") == "active slot_a\n"


def test_persist_active_slot_map_refuses_symlinked_map_without_touching_target(tmp_path):
    store = LocalDockerRouterStateStore(tmp_path / "router-state")
    initial = store.persist(scope(), bindings(), active_slot=None)
    outside = tmp_path / "outside-map"
    outside.write_text("outside\n", encoding="utf-8")
    os.chmod(outside, 0o600)
    Path(initial.record.active_slot_map_path).unlink()
    Path(initial.record.active_slot_map_path).symlink_to(outside)
    result = store.persist_active_slot_map(
        initial.record, expected_active_slot=None, active_slot="slot_b"
    )
    assert result.status == "failed"
    assert outside.read_text(encoding="utf-8") == "outside\n"
