from runtime.dashboard_cli import write_dashboard
from runtime.dashboard_api import DashboardQuery
from runtime.observability_dashboard import ObservabilityDashboard
from runtime.task import Task
from runtime.tracing import Tracer


def test_write_dashboard_creates_utf8_self_contained_html(tmp_path):
    task = Task(id="TASK-001", title="Expense tracker", description="x", role="developer", status="completed")
    output = write_dashboard(
        [task],
        tmp_path / "ops" / "dashboard.html",
        project_id="PROJECT-001",
        query=DashboardQuery(ObservabilityDashboard(tracer=Tracer())),
    )

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "AI-Team Operational Dashboard" in content
    assert "Expense tracker" in content
    assert "PROJECT-001" in content
    assert "<script" not in content.lower()
