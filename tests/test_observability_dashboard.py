from runtime.observability_dashboard import ObservabilityDashboard
from runtime.task import Task
from runtime.tracing import Tracer


def _task(task_id, role, status):
    return Task(id=task_id, title=task_id, description="dashboard", role=role, status=status)


def test_dashboard_empty_state_is_valid():
    snapshot = ObservabilityDashboard(tracer=Tracer()).snapshot([])
    assert snapshot.workflow.total_tasks == 0
    assert snapshot.workflow.success_rate == 0.0
    assert snapshot.tasks == ()
    assert snapshot.agents == ()


def test_dashboard_aggregates_workflow_and_agent_status():
    tasks = [
        _task("TASK-001", "developer", "completed"),
        _task("TASK-002", "developer", "failed"),
        _task("TASK-003", "tester", "running"),
        _task("TASK-004", "reviewer", "pending"),
        _task("TASK-005", "reviewer", "blocked"),
    ]
    snapshot = ObservabilityDashboard(tracer=Tracer()).snapshot(tasks, project_id="PROJECT-001")

    assert snapshot.project_id == "PROJECT-001"
    assert snapshot.workflow.total_tasks == 5
    assert snapshot.workflow.completed == 1
    assert snapshot.workflow.failed == 1
    assert snapshot.workflow.blocked == 1
    assert snapshot.workflow.active == 1
    assert snapshot.workflow.pending == 1
    assert snapshot.workflow.success_rate == 0.2

    agents = {item.role: item for item in snapshot.agents}
    assert agents["developer"].task_count == 2
    assert agents["developer"].completed == 1
    assert agents["developer"].failed == 1
    assert agents["tester"].active == 1


def test_dashboard_links_task_to_root_trace_identity():
    tracer = Tracer()
    task = _task("TASK-TRACE", "developer", "completed")
    with tracer.span("workflow.task", attributes={"task_id": task.id}):
        pass

    item = ObservabilityDashboard(tracer=tracer).snapshot([task]).tasks[0]
    assert item.trace_id is not None
    assert item.root_span_id is not None


def test_dashboard_does_not_expose_trace_identity_as_metric_dimension():
    snapshot = ObservabilityDashboard(tracer=Tracer()).snapshot([_task("TASK-001", "developer", "completed")])
    assert "trace_id" not in snapshot.workflow.__dict__
    assert "span_id" not in snapshot.workflow.__dict__
