from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager


def _ready_task(task_id: str) -> Task:
    return Task(
        id=task_id,
        title=task_id,
        description="concurrency contract",
        role="developer",
        status="ready",
    )


def test_concurrent_same_task_transition_commits_once():
    task = _ready_task("TASK-CONC-001")
    manager = TaskManager([task])

    def attempt():
        try:
            manager.mark_running(task.id)
            return "success"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=16) as executor:
        outcomes = list(executor.map(lambda _: attempt(), range(64)))

    assert outcomes.count("success") == 1
    assert outcomes.count("rejected") == 63
    assert task.status == "running"
    assert task.status_history == [
        {"from": "ready", "to": "running"},
    ]


def test_concurrent_independent_tasks_keep_result_error_and_history_isolated():
    tasks = [_ready_task(f"TASK-CONC-{index:03d}") for index in range(24)]
    manager = TaskManager(tasks)

    def execute(task: Task):
        manager.mark_running(task.id)
        if int(task.id.rsplit("-", 1)[1]) % 2:
            manager.mark_failed(task.id, f"failure-{task.id}")
        else:
            manager.mark_completed(
                task.id,
                {"message": f"success-{task.id}"},
            )
        return task.id

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(execute, task) for task in tasks]
        assert {future.result() for future in as_completed(futures)} == {
            task.id for task in tasks
        }

    for task in tasks:
        suffix = int(task.id.rsplit("-", 1)[1])
        assert len(task.status_history) == 2
        assert task.status_history[0] == {
            "from": "ready",
            "to": "running",
        }

        if suffix % 2:
            assert task.status == "failed"
            assert task.error == f"failure-{task.id}"
            assert task.result == {}
        else:
            assert task.status == "completed"
            assert task.error is None
            assert task.result["message"] == f"success-{task.id}"


def test_concurrent_read_queries_never_break_task_manager_state():
    tasks = [_ready_task(f"TASK-READ-{index:03d}") for index in range(32)]
    manager = TaskManager(tasks)

    def complete(task: Task):
        manager.mark_running(task.id)
        manager.mark_completed(task.id, {"task": task.id})

    def observe(_):
        return (
            manager.is_finished(),
            manager.has_failed_tasks(),
            len(manager.get_failed_tasks()),
            len(manager.get_blocked_tasks()),
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(complete, task) for task in tasks]
        observations = list(executor.map(observe, range(128)))
        for future in futures:
            future.result()

    assert all(observation[2] == 0 for observation in observations)
    assert all(observation[3] == 0 for observation in observations)
    assert manager.is_finished() is True
    assert manager.has_failed_tasks() is False


def test_concurrent_scheduler_calls_promote_each_ready_task_once():
    tasks = [
        Task(
            id=f"TASK-SCHED-{index:03d}",
            title="scheduler",
            description="concurrency contract",
            role="developer",
        )
        for index in range(32)
    ]
    manager = TaskManager(tasks)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: manager.get_ready_tasks(), range(16)))

    flattened = [task.id for batch in results for task in batch]
    assert len(flattened) == 32
    assert len(set(flattened)) == 32

    for task in tasks:
        assert task.status == "ready"
        assert task.status_history == [
            {"from": "pending", "to": "ready"},
        ]


def test_invalid_concurrent_transition_does_not_corrupt_history():
    task = _ready_task("TASK-CONC-INVALID")
    manager = TaskManager([task])

    def attempt():
        try:
            manager.mark_completed(task.id)
        except ValueError as exc:
            return str(exc)
        return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        errors = list(executor.map(lambda _: attempt(), range(32)))

    assert all(error is not None for error in errors)
    assert task.status == "ready"
    assert task.status_history == []


def test_task_manager_lock_is_reentrant_for_nested_lifecycle_operations():
    task = _ready_task("TASK-CONC-REENTRANT")
    manager = TaskManager([task])

    # Lifecycle methods call other TaskManager methods while the manager
    # lock is held. RLock keeps that nesting legal without deadlock.
    manager.mark_running(task.id)
    manager.mark_completed(task.id, {"message": "done"})

    assert task.status == "completed"
    assert task.result["message"] == "done"
    assert len(task.status_history) == 2
