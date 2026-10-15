import pytest

from runtime.project_execution_checkpoint import (
    ProjectExecutionCheckpoint,
    ProjectExecutionCheckpointError,
    ProjectExecutionCheckpointStore,
)
from runtime.project_scheduler import ProjectExecutionScope
from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.workflow_checkpoint import WorkflowCheckpoint


def _checkpoint(*, status: str = "started", reservation_id: str = "RES-001", project_id: str = "P1") -> ProjectExecutionCheckpoint:
    task = Task(
        "TASK-001",
        "task",
        "description",
        "developer",
        status=TaskStatus.RUNNING.value,
        context={"project_id": project_id},
    )
    return ProjectExecutionCheckpoint(
        reservation_id=reservation_id,
        scope=ProjectExecutionScope(project_id),
        task_id=task.id,
        status=status,
        task_checkpoint=WorkflowCheckpoint.capture(task),
    )


def test_checkpoint_round_trip_is_immutable_and_scope_bound():
    checkpoint = _checkpoint()
    payload = checkpoint.to_dict()
    restored = ProjectExecutionCheckpoint.from_dict(payload)

    assert restored.to_dict() == payload
    assert restored.project_id == "P1"
    assert restored.recoverable is True
    assert restored.task_checkpoint.restore().context["project_id"] == "P1"

    payload["task_checkpoint"]["task"]["context"]["project_id"] = "P2"
    assert checkpoint.project_id == "P1"
    assert checkpoint.task_checkpoint.restore().context["project_id"] == "P1"


def test_checkpoint_rejects_identity_status_and_task_mismatches():
    checkpoint = _checkpoint()

    with pytest.raises(ProjectExecutionCheckpointError):
        ProjectExecutionCheckpoint.from_dict({**checkpoint.to_dict(), "status": "unknown"})

    with pytest.raises(ProjectExecutionCheckpointError):
        ProjectExecutionCheckpoint.from_dict({**checkpoint.to_dict(), "task_id": "TASK-OTHER"})

    with pytest.raises(ProjectExecutionCheckpointError):
        ProjectExecutionCheckpoint.from_dict({**checkpoint.to_dict(), "project_id": ""})

    mismatched = checkpoint.to_dict()
    mismatched["project_id"] = "P2"
    with pytest.raises(ProjectExecutionCheckpointError, match="project scope"):
        ProjectExecutionCheckpoint.from_dict(mismatched)


def test_store_persists_and_filters_recoverable_checkpoints(tmp_path):
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    started = _checkpoint(status="started", reservation_id="RES-001")
    completed = _checkpoint(status="completed", reservation_id="RES-002")

    store.save(started)
    store.save(completed)

    assert store.load("RES-001").to_dict() == started.to_dict()
    assert [item.reservation_id for item in store.list_all()] == ["RES-001", "RES-002"]
    assert [item.reservation_id for item in store.list_recoverable()] == ["RES-001"]
    assert [item.reservation_id for item in store.list_recoverable("P1")] == ["RES-001"]


def test_store_replaces_checkpoint_atomically_and_deletes_by_identity(tmp_path):
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    started = _checkpoint(status="started")
    released = _checkpoint(status="released")

    store.save(started)
    store.save(released)
    assert store.load("RES-001").status == "released"
    assert store.list_recoverable() == ()

    store.delete("RES-001")
    with pytest.raises(KeyError):
        store.load("RES-001")
    with pytest.raises(KeyError):
        store.delete("RES-001")


def test_store_rejects_invalid_or_path_like_reservation_ids(tmp_path):
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    with pytest.raises(ValueError):
        store.load("../escape")
    with pytest.raises(ValueError):
        store.delete("")
