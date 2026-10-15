import pytest

from runtime.dashboard_api import DashboardQuery
from runtime.observability_dashboard import ObservabilityDashboard
from runtime.task import Task
from runtime.tracing import Tracer


def _task(task_id, role="developer", status="completed"):
    return Task(id=task_id, title=task_id, description="dashboard", role=role, status=status)


def _query():
    return DashboardQuery(ObservabilityDashboard(tracer=Tracer()))


def test_dashboard_query_exposes_stable_read_operations():
    query = _query()
    tasks = [_task("TASK-001"), _task("TASK-002", "tester", "running")]

    snapshot = query.snapshot(tasks, project_id="PROJECT-001")
    workflow = query.workflow(tasks, project_id="PROJECT-001")
    agents = query.agents(tasks, project_id="PROJECT-001")
    task = query.task(tasks, "TASK-001", project_id="PROJECT-001")

    assert snapshot.project_id == "PROJECT-001"
    assert workflow.total_tasks == 2
    assert {item.role for item in agents} == {"developer", "tester"}
    assert task.task_id == "TASK-001"


def test_dashboard_query_task_lookup_is_exact_and_read_only():
    query = _query()
    tasks = [_task("TASK-001")]
    before = tasks[0].to_dict()

    with pytest.raises(KeyError):
        query.task(tasks, "TASK-999")

    assert tasks[0].to_dict() == before


def test_dashboard_query_rejects_invalid_task_id():
    query = _query()
    with pytest.raises(ValueError):
        query.task([], "")
    with pytest.raises(ValueError):
        query.task([], "   ")
