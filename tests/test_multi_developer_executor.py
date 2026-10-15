from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time

import pytest

from agents.base import BaseAgent
from runtime.agent_config import AgentConfig
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.base import BaseLLM
from runtime.multi_developer_executor import MultiDeveloperExecutor
from runtime.task import Task
from runtime.task_manager import TaskManager


class _LLM(BaseLLM):
    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return "ok"


class _Developer(BaseAgent):
    def __init__(self, developer_id):
        super().__init__(
            AgentConfig(role="developer", model="test", extra={"developer_id": developer_id}),
            llm=_LLM(),
        )

    @property
    def role(self):
        return "developer"

    def run(self, task):
        return AgentResult(
            status="completed",
            agent="developer",
            task_id=task.id,
            message="completed",
        )


class _Workflow:
    def __init__(self, manager, developer, barrier=None, active=None, peak=None, lock=None):
        self.manager = manager
        self.developer = developer
        self.barrier = barrier
        self.active = active
        self.peak = peak
        self.lock = lock

    def execute(self, task_id):
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        if self.active is not None:
            with self.lock:
                self.active[0] += 1
                self.peak[0] = max(self.peak[0], self.active[0])
            time.sleep(0.05)
            with self.lock:
                self.active[0] -= 1
        self.manager.mark_completed(task_id, {"developer_id": self.developer.config.extra["developer_id"]})
        return self.manager.get_task(task_id)


def _manager(count=6):
    return TaskManager([
        Task(
            id=f"TASK-MD-{index:03d}",
            title="parallel task",
            description="independent work",
            role="developer",
        )
        for index in range(count)
    ])


def _router():
    router = AgentRouter()
    router.register_developer_pool([_Developer("developer-1"), _Developer("developer-2"), _Developer("developer-3")])
    return router


def test_executor_claims_each_ready_task_once_and_assigns_developer():
    manager = _manager(12)
    router = _router()
    seen = []
    lock = Lock()

    def factory(developer):
        class Workflow:
            def execute(self, task_id):
                with lock:
                    seen.append((task_id, developer.config.extra["developer_id"]))
                manager.mark_completed(task_id, {"developer_id": developer.config.extra["developer_id"]})
                return manager.get_task(task_id)

        return Workflow()

    executor = MultiDeveloperExecutor(manager, router, factory, max_workers=3)
    results = executor.run_until_idle()

    assert {task.id for task in results} == {task.id for task in manager.get_all_tasks()}
    assert len(seen) == 12
    assert len({task_id for task_id, _ in seen}) == 12
    assert all(task.status == "completed" for task in manager.get_all_tasks())
    assert {developer_id for _, developer_id in seen} <= {"developer-1", "developer-2", "developer-3"}


def test_executor_runs_independent_tasks_concurrently():
    manager = _manager(6)
    router = _router()
    active = [0]
    peak = [0]
    lock = Lock()

    def factory(developer):
        return _Workflow(manager, developer, active=active, peak=peak, lock=lock)

    executor = MultiDeveloperExecutor(manager, router, factory, max_workers=3)
    executor.run_until_idle()

    assert peak[0] >= 2
    assert all(task.status == "completed" for task in manager.get_all_tasks())


def test_executor_respects_dependency_layers():
    tasks = [
        Task(id="TASK-ROOT-A", title="A", description="A", role="developer"),
        Task(id="TASK-ROOT-B", title="B", description="B", role="developer"),
        Task(id="TASK-CHILD", title="C", description="C", role="developer", dependencies=["TASK-ROOT-A", "TASK-ROOT-B"]),
    ]
    manager = TaskManager(tasks)
    router = _router()
    order = []
    lock = Lock()

    def factory(developer):
        class Workflow:
            def execute(self, task_id):
                with lock:
                    order.append(task_id)
                manager.mark_completed(task_id)
                return manager.get_task(task_id)

        return Workflow()

    MultiDeveloperExecutor(manager, router, factory, max_workers=3).run_until_idle()

    assert order[-1] == "TASK-CHILD"
    assert set(order[:2]) == {"TASK-ROOT-A", "TASK-ROOT-B"}


def test_concurrent_external_claims_cannot_start_same_task_twice():
    manager = _manager(1)
    task = manager.get_all_tasks()[0]
    manager.mark_ready(task.id)
    barrier = Barrier(16)

    def claim():
        barrier.wait(timeout=5)
        try:
            manager.mark_running(task.id)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(16)))

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 15
    assert task.status == "running"


def test_executor_rejects_more_workers_than_developers():
    manager = _manager(2)
    router = _router()

    with pytest.raises(ValueError, match="max_workers"):
        MultiDeveloperExecutor(manager, router, lambda _: object(), max_workers=4)
