from runtime.dashboard_html import render_dashboard
from runtime.observability_dashboard import ObservabilityDashboard
from runtime.task import Task
from runtime.tracing import Tracer


def test_dashboard_renderer_returns_read_only_html_with_operational_sections():
    task = Task(id="TASK-001", title="<unsafe>", description="x", role="developer", status="completed")
    snapshot = ObservabilityDashboard(tracer=Tracer()).snapshot([task], project_id="PROJECT-001")
    html = render_dashboard(snapshot)

    assert html.startswith("<!doctype html>")
    assert "AI-Team Operational Dashboard" in html
    assert "PROJECT-001" in html
    assert "&lt;unsafe&gt;" in html
    assert "Agents" in html
    assert "Tasks" in html
    assert "TASK-001" in html
    assert "<script" not in html.lower()


def test_dashboard_renderer_handles_empty_snapshot():
    snapshot = ObservabilityDashboard(tracer=Tracer()).snapshot([])
    html = render_dashboard(snapshot)
    assert "No agent data" in html
    assert "No task data" in html
