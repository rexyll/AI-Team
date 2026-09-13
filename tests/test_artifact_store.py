from __future__ import annotations

import hashlib

import pytest

from runtime.artifact_store import FilesystemArtifactStore


def test_store_and_read_round_trip(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    record = store.store("x" * 1000, kind="tool_output", task_id="TASK-1")

    assert record.size == 1000
    assert record.checksum == hashlib.sha256(b"x" * 1000).hexdigest()
    assert record.task_id == "TASK-1"
    assert store.read_text(record.artifact_id) == "x" * 1000


def test_binary_round_trip_and_default_mime(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    record = store.store(b"\x00\x01\xff", kind="log")

    assert record.mime_type == "application/octet-stream"
    assert store.read_bytes(record.artifact_id) == b"\x00\x01\xff"


def test_identical_content_shares_one_object_but_keeps_distinct_records(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    first = store.store("same content", kind="tool_output")
    second = store.store("same content", kind="tool_output")

    assert first.artifact_id != second.artifact_id
    assert first.checksum == second.checksum
    assert first.path == second.path
    assert store.read_text(second.artifact_id) == "same content"


def test_records_survive_store_reopening(tmp_path):
    root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(root)
    record = store.store("persistent payload", kind="tool_output", metadata={"tool": "run_command"})

    reopened = FilesystemArtifactStore(root)
    restored = reopened.get(record.artifact_id)

    assert restored == record
    assert restored.metadata == {"tool": "run_command"}
    assert reopened.read_text(record.artifact_id) == "persistent payload"


def test_get_missing_and_invalid_inputs(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    with pytest.raises(KeyError):
        store.get("missing")
    with pytest.raises(ValueError):
        store.store("x", kind="")
    with pytest.raises(TypeError):
        store.store("x", kind="tool_output", metadata=["not", "a", "dict"])
    with pytest.raises(TypeError):
        store.store(123, kind="tool_output")


def test_read_detects_checksum_mismatch(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    record = store.store("integrity matters", kind="tool_output")

    with open(record.path, "ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ValueError, match="checksum"):
        store.read_text(record.artifact_id)


def test_delete_removes_record_and_last_object(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    record = store.store("unique payload", kind="tool_output")

    store.delete(record.artifact_id)

    with pytest.raises(KeyError):
        store.get(record.artifact_id)
    assert not store._object_path(record.checksum).exists()


def test_delete_keeps_object_when_other_records_reference_it(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    first = store.store("shared payload", kind="tool_output")
    second = store.store("shared payload", kind="tool_output")

    store.delete(first.artifact_id)

    assert store.read_text(second.artifact_id) == "shared payload"
