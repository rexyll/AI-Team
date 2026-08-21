import threading
import time

import pytest

from runtime.task import Task
from runtime.task_executor import TaskLayerExecutor


def _task(task_id):
    return Task(
        id=task_id,
        title=task_id,
        description="executor test",
        role="developer",
    )


def test_executor_runs_layer_concurrently_with_bounded_workers():
    executor = TaskLayerExecutor(max_workers=2)
    tasks = [_task("TASK-001"), _task("TASK-002"), _task("TASK-003")]
    active = 0
    peak = 0
    lock = threading.Lock()

    def execute(task):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return task.id

    assert executor.run_layer(tasks, execute) == [
        "TASK-001",
        "TASK-002",
        "TASK-003",
    ]
    assert peak == 2


def test_executor_preserves_result_order():
    executor = TaskLayerExecutor(max_workers=3)
    tasks = [_task("TASK-001"), _task("TASK-002"), _task("TASK-003")]

    def execute(task):
        if task.id == "TASK-001":
            time.sleep(0.03)
        return task.id

    assert executor.run_layer(tasks, execute) == [
        "TASK-001",
        "TASK-002",
        "TASK-003",
    ]


def test_executor_waits_for_all_peers_before_raising_worker_error():
    executor = TaskLayerExecutor(max_workers=3)
    tasks = [_task("TASK-001"), _task("TASK-002"), _task("TASK-003")]
    completed = []
    lock = threading.Lock()

    def execute(task):
        time.sleep(0.02)
        with lock:
            completed.append(task.id)
        if task.id == "TASK-002":
            raise RuntimeError("boom")
        return task.id

    with pytest.raises(RuntimeError, match="boom"):
        executor.run_layer(tasks, execute)

    assert sorted(completed) == ["TASK-001", "TASK-002", "TASK-003"]


def test_executor_does_not_mutate_task_lifecycle():
    executor = TaskLayerExecutor(max_workers=2)
    tasks = [_task("TASK-001"), _task("TASK-002")]
    before = [(task.status, list(task.status_history), task.error) for task in tasks]

    executor.run_layer(tasks, lambda task: task.id)

    after = [(task.status, list(task.status_history), task.error) for task in tasks]
    assert after == before


def test_executor_rejects_invalid_worker_count():
    with pytest.raises(TypeError):
        TaskLayerExecutor(max_workers="2")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        TaskLayerExecutor(max_workers=0)


def test_executor_rejects_invalid_execute_callable():
    with pytest.raises(TypeError, match="callable"):
        TaskLayerExecutor().run_layer([_task("TASK-001")], None)  # type: ignore[arg-type]
