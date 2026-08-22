from __future__ import annotations

from threading import Lock

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT_ID = "PROJECT-LONG-RUNNING-001"
TASK_COUNT = 32


class LongRunningDeveloper:
    role = "developer"

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self._lock = Lock()

    def run(self, task: Task) -> dict:
        with self._lock:
            self.calls[task.id] = self.calls.get(task.id, 0) + 1
            call = self.calls[task.id]
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": f"implementation round {call}",
        }


class LongRunningReviewer:
    role = "reviewer"

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self._lock = Lock()

    def run(self, task: Task) -> dict:
        with self._lock:
            self.calls[task.id] = self.calls.get(task.id, 0) + 1
            call = self.calls[task.id]
        if call == 1:
            return {
                "status": "revision",
                "agent": "reviewer",
                "task_id": task.id,
                "message": "tighten implementation",
            }
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "approved",
        }


def _manager() -> TaskManager:
    return TaskManager(
        [
            Task(
                id=f"TASK-LONG-{index:03d}",
                title=f"long-running task {index}",
                description="exercise bounded parallel workflow execution",
                role="developer",
            )
            for index in range(1, TASK_COUNT + 1)
        ]
    )


def test_many_parallel_workflow_tasks_preserve_lifecycle_and_persisted_query_semantics(tmp_path):
    manager = _manager()
    developer = LongRunningDeveloper()
    reviewer = LongRunningReviewer()
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)

    persistence = WorkflowEventPersistenceAdapter(tmp_path / "events")
    log = WorkflowEventLog(persistence_sink=persistence)

    orchestrator = Orchestrator(
        task_manager=manager,
        agent_router=router,
        max_workers=4,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    )
    orchestrator.run()

    tasks = manager.get_all_tasks()
    assert len(tasks) == TASK_COUNT
    assert all(task.status == "completed" for task in tasks)
    assert all(task.review_round == 2 for task in tasks)
    assert all(developer.calls[task.id] == 2 for task in tasks)
    assert all(reviewer.calls[task.id] == 2 for task in tasks)

    # One initial start, two developer completions, two review starts,
    # one revision request, and one final approval per task. The tester is
    # intentionally absent, so each workflow round also emits tester_skipped.
    expected_events_per_task = 9
    assert len(log) == TASK_COUNT * expected_events_per_task

    # Parallel execution makes the global append order scheduler-dependent.
    # Persistence exposes IDs in deterministic filename order, while the log
    # exposes canonical workflow-event order. The durable and in-memory
    # representations must therefore agree on event identity, not incidental
    # cross-task scheduling order.
    assert set(persistence.list_ids()) == {event.event_id for event in log.list_all()}

    for task in tasks:
        event_types = [event.event_type for event in log.list_for_task(task.id)]
        assert event_types == [
            "task_started",
            "developer_completed",
            "tester_skipped",
            "review_started",
            "reviewer_revision_requested",
            "developer_completed",
            "tester_skipped",
            "review_started",
            "reviewer_approved",
        ]

    query = WorkflowEventQueryService.from_persistence(
        persistence,
        project_id=PROJECT_ID,
    )
    assert query.lifecycle() == "completed"
    assert len(query.as_dict()["tasks"]) == TASK_COUNT

    for task in tasks:
        assert query.lifecycle(task.id) == "completed"
        assert query.review_status(task.id) == "approved"
        assert query.retry(task.id) == {"retry_attempt": 0, "max_retries": 0}
        assert query.error(task.id) is None
