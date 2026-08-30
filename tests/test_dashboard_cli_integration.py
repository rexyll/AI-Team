from pathlib import Path

from main import build_parser
from runtime.dashboard_cli import write_dashboard
from runtime.task_manager import TaskManager


def test_cli_parser_accepts_dashboard_output_path():
    args = build_parser().parse_args(["build something", "--dashboard", "out/dashboard.html"])
    assert args.requirement == "build something"
    assert args.dashboard == "out/dashboard.html"


def test_dashboard_export_writes_utf8_html(tmp_path: Path):
    task_manager = TaskManager([])
    output = tmp_path / "dashboard.html"
    write_dashboard(task_manager.get_all_tasks(), output, project_id="PROJECT-CLI")
    content = output.read_text(encoding="utf-8")
    assert "AI-Team Operational Dashboard" in content
    assert "PROJECT-CLI" in content
