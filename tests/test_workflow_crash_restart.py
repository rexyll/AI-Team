from runtime.persistent_task_manager import PersistentTaskManager
from runtime.task import Task
from runtime.task_state_store import InMemoryTaskStateStore
from runtime.task_status import TaskStatus
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_recovery import WorkflowRecovery
from runtime.workflow_resume import WorkflowResumePlanner


def _manager(store):
    tasks = [
        Task("TASK-DONE", "done", "completed work", "developer"),
        Task("TASK-RESUME", "resume", "unfinished work", "developer"),
    ]
    tasks[0].status = TaskStatus.COMPLETED.value
    tasks[0].status_history.append({"from": TaskStatus.RUNNING.value, "to": TaskStatus.COMPLETED.value})
    tasks[1].status = TaskStatus.READY.value
    return PersistentTaskManager(tasks, state_store=store)


def test_crash_restart_recovers_completed_and_resumable_state_without_replaying_completion():
    store = InMemoryTaskStateStore()
    manager = _manager(store)
    before = store.snapshot()

    checkpoints = [
        WorkflowCheckpoint.capture(manager.get_task("TASK-DONE")),
        WorkflowCheckpoint.capture(manager.get_task("TASK-RESUME")),
    ]
    recovered_tasks = WorkflowRecovery().recover_tasks(checkpoints).tasks

    # WorkflowExecutionState exposes an immutable tuple; TaskManager intentionally
    # requires a concrete list of tasks at construction time.
    restarted = PersistentTaskManager(list(recovered_tasks), state_store=store, persist_initial=False)
    plan = WorkflowResumePlanner().plan(restarted.list_tasks())

    assert plan.resumable_task_ids == ("TASK-RESUME",)
    assert restarted.get_task("TASK-DONE").status == TaskStatus.COMPLETED.value
    assert restarted.get_task("TASK-DONE").status_history == [
        {"from": TaskStatus.RUNNING.value, "to": TaskStatus.COMPLETED.value}
    ]
    assert store.snapshot() == before
