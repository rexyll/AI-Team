from runtime.recovery_replan_replacement import ReplanGraphReplacement
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id="TASK-001",
                title="done",
                description="done",
                role="developer",
                status=TaskStatus.COMPLETED.value,
                result={"data": {"answer": "kept"}},
            ),
            Task(
                id="TASK-002",
                title="old",
                description="old",
                role="developer",
                status=TaskStatus.FAILED.value,
            ),
        ]
    )


def test_replace_task_graph_swaps_atomically_and_preserves_completed_history():
    manager = _manager()
    completed = manager.get_task("TASK-001")
    replacement = ReplanGraphReplacement(
        tasks=(
            Task(
                id="TASK-001",
                title="updated",
                description="updated",
                role="developer",
                status=TaskStatus.COMPLETED.value,
                result={"data": {"answer": "kept"}},
            ),
            Task(id="TASK-003", title="new", description="new", role="developer"),
        )
    )

    manager.replace_task_graph(replacement.tasks)

    assert manager.get_task("TASK-001").status == TaskStatus.COMPLETED.value
    assert manager.get_task("TASK-001").result == completed.result
    assert manager.get_task("TASK-001").title == "updated"
    assert manager.get_task("TASK-003").status == TaskStatus.PENDING.value
    assert {task.id for task in manager.get_all_tasks()} == {"TASK-001", "TASK-003"}


def test_replace_task_graph_rechecks_active_state_inside_owner_boundary():
    manager = TaskManager(
        [
            Task(
                id="TASK-001",
                title="done",
                description="done",
                role="developer",
                status=TaskStatus.COMPLETED.value,
            ),
            Task(
                id="TASK-002",
                title="active",
                description="active",
                role="developer",
                status=TaskStatus.READY.value,
            ),
        ]
    )
    replacement = [
        Task(id="TASK-001", title="done", description="done", role="developer", status=TaskStatus.COMPLETED.value),
        Task(id="TASK-003", title="new", description="new", role="developer"),
    ]

    try:
        manager.replace_task_graph(replacement)
    except RuntimeError as exc:
        assert "active" in str(exc)
    else:
        raise AssertionError("active graph replacement must be rejected")

    assert {task.id for task in manager.get_all_tasks()} == {"TASK-001", "TASK-002"}


def test_replace_task_graph_rejects_duplicate_ids_without_mutating_live_graph():
    manager = _manager()
    replacement = [
        Task(id="TASK-001", title="a", description="a", role="developer"),
        Task(id="TASK-001", title="b", description="b", role="developer"),
    ]

    try:
        manager.replace_task_graph(replacement)
    except ValueError as exc:
        assert "Duplicate task id" in str(exc)
    else:
        raise AssertionError("duplicate ids must be rejected")

    assert {task.id for task in manager.get_all_tasks()} == {"TASK-001", "TASK-002"}
