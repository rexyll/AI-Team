from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT_ID = "PROJECT-8-6-5-001"


class _Developer:
    role = "developer"

    def __init__(self, *, flaky: set[str] | None = None, delay: float = 0.0) -> None:
        self.flaky = set(flaky or ())
        self.delay = delay
        self.calls: dict[str, int] = {}
        self._lock = threading.Lock()

    def run(self, task: Task) -> dict:
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            call = self.calls.get(task.id, 0) + 1
            self.calls[task.id] = call
        if task.id in self.flaky and call == 1:
            raise RuntimeError(f"transient failure for {task.id}")
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": f"implemented {call}",
        }


class _Reviewer:
    role = "reviewer"

    def __init__(self, *, revise: set[str] | None = None) -> None:
        self.revise = set(revise or ())
        self.calls: dict[str, int] = {}
        self._lock = threading.Lock()

    def run(self, task: Task) -> dict:
        with self._lock:
            call = self.calls.get(task.id, 0) + 1
            self.calls[task.id] = call
        if task.id in self.revise and call == 1:
            return {
                "status": "revision",
                "agent": "reviewer",
                "task_id": task.id,
                "message": "revise implementation",
            }
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "approved",
        }


class _FailOnceSink:
    def __init__(self, delegate: WorkflowEventPersistenceAdapter) -> None:
        self.delegate = delegate
        self._failed = False
        self._lock = threading.Lock()

    def save_if_absent(self, event) -> bool:
        with self._lock:
            if not self._failed:
                self._failed = True
                raise OSError("transient event persistence failure")
        return self.delegate.save_if_absent(event)


def _router(developer: _Developer, reviewer: _Reviewer) -> AgentRouter:
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    return router


def _tasks(count: int, *, retry_ids: set[str] | None = None) -> list[Task]:
    retry_ids = retry_ids or set()
    tasks = []
    for index in range(1, count + 1):
        task_id = f"TASK-8-6-5-{index:03d}"
        task = Task(
            id=task_id,
            title=f"matrix task {index}",
            description="exercise failure and concurrency boundaries",
            role="developer",
        )
        if task_id in retry_ids:
            task.configure_retry(max_retries=1)
        tasks.append(task)
    return tasks


def test_worker_event_persistence_failure_recovers_without_memory_publication(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    sink = _FailOnceSink(adapter)
    log = WorkflowEventLog(persistence_sink=sink)
    developer = _Developer()
    reviewer = _Reviewer()
    manager = TaskManager(_tasks(1, retry_ids={"TASK-8-6-5-001"}))

    orchestrator = Orchestrator(
        manager,
        _router(developer, reviewer),
        max_workers=1,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    )
    orchestrator.run()

    task = manager.get_task("TASK-8-6-5-001")
    assert task.status == "completed"
    assert task.retry_attempt == 1
    assert developer.calls[task.id] == 1
    assert set(adapter.list_ids()) == {event.event_id for event in log.list_all()}
    assert all(event.event_type != "task_started" or event.payload.get("status") == "running" for event in log.list_all())
    assert any(event.event_type == "task_failed" for event in log.list_all())
    assert any(event.event_type == "task_retrying" for event in log.list_all())


def test_query_can_run_during_parallel_worker_execution_without_mutating_events(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    log = WorkflowEventLog(persistence_sink=adapter)
    developer = _Developer(delay=0.01)
    reviewer = _Reviewer()
    manager = TaskManager(_tasks(12))
    orchestrator = Orchestrator(
        manager,
        _router(developer, reviewer),
        max_workers=4,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(orchestrator.run)
        observed_sizes: list[int] = []
        while not future.done():
            snapshot_ids = tuple(event.event_id for event in log.list_all())
            observed_sizes.append(len(snapshot_ids))
            assert len(snapshot_ids) == len(set(snapshot_ids))
            query = WorkflowEventQueryService.from_persistence(adapter, project_id=PROJECT_ID)
            assert len(query.as_dict()["tasks"]) <= 12
            time.sleep(0.001)
        future.result()

    assert observed_sizes
    assert all(task.status == "completed" for task in manager.get_all_tasks())
    assert set(adapter.list_ids()) == {event.event_id for event in log.list_all()}
    assert WorkflowEventQueryService.from_persistence(
        adapter, project_id=PROJECT_ID
    ).lifecycle() == "completed"


def test_partial_failure_retry_and_reviewer_revision_can_progress_concurrently(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    log = WorkflowEventLog(persistence_sink=adapter)
    retry_id = "TASK-8-6-5-001"
    revision_id = "TASK-8-6-5-002"
    developer = _Developer(flaky={retry_id}, delay=0.005)
    reviewer = _Reviewer(revise={revision_id})
    manager = TaskManager(_tasks(6, retry_ids={retry_id}))

    orchestrator = Orchestrator(
        manager,
        _router(developer, reviewer),
        max_workers=4,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    )
    orchestrator.run()

    assert all(task.status == "completed" for task in manager.get_all_tasks())
    assert manager.get_task(retry_id).retry_attempt == 1
    assert manager.get_task(revision_id).review_round == 2
    assert any(event.event_type == "task_retrying" and event.task_id == retry_id for event in log.list_all())
    assert any(
        event.event_type == "reviewer_revision_requested" and event.task_id == revision_id
        for event in log.list_all()
    )
    assert set(adapter.list_ids()) == {event.event_id for event in log.list_all()}


def test_concurrent_review_revision_and_query_preserve_project_semantics(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    log = WorkflowEventLog(persistence_sink=adapter)
    revision_ids = {
        "TASK-8-6-5-001",
        "TASK-8-6-5-003",
        "TASK-8-6-5-005",
    }
    developer = _Developer(delay=0.008)
    reviewer = _Reviewer(revise=revision_ids)
    manager = TaskManager(_tasks(8))
    orchestrator = Orchestrator(
        manager,
        _router(developer, reviewer),
        max_workers=4,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        run_future = executor.submit(orchestrator.run)
        query_errors: list[BaseException] = []

        def observe() -> None:
            while not run_future.done():
                try:
                    WorkflowEventQueryService.from_persistence(
                        adapter, project_id=PROJECT_ID
                    ).as_dict()
                    log.list_for_project(PROJECT_ID)
                except BaseException as exc:  # pragma: no cover - contract guard
                    query_errors.append(exc)
                time.sleep(0.001)

        observe_future = executor.submit(observe)
        run_future.result()
        observe_future.result()

    assert not query_errors
    assert all(task.status == "completed" for task in manager.get_all_tasks())
    for task_id in revision_ids:
        assert manager.get_task(task_id).review_round == 2
        assert WorkflowEventQueryService.from_persistence(
            adapter, project_id=PROJECT_ID
        ).review_status(task_id) == "approved"


def test_checkpoint_failure_does_not_create_duplicate_events_on_explicit_resume_boundary(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    log = WorkflowEventLog(persistence_sink=adapter)
    developer = _Developer()
    reviewer = _Reviewer()
    manager = TaskManager(_tasks(1))
    checkpoint_calls = 0

    def checkpoint(_manager: TaskManager) -> None:
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        if checkpoint_calls == 2:
            raise OSError("checkpoint failure")

    orchestrator = Orchestrator(
        manager,
        _router(developer, reviewer),
        max_workers=1,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    )
    orchestrator.set_state_change_hook(checkpoint)

    try:
        orchestrator.run()
    except OSError as exc:
        assert str(exc) == "checkpoint failure"

    event_ids_before = tuple(adapter.list_ids())
    assert len(event_ids_before) == len(set(event_ids_before))
    assert set(event_ids_before) == {event.event_id for event in log.list_all()}
    assert manager.get_task("TASK-8-6-5-001").status in {"running", "review_pending", "reviewing", "completed"}
