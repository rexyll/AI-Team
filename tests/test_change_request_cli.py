import json
from types import SimpleNamespace

import pytest

import main
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def definition(task_id, title="original", dependencies=None):
    return {"id": task_id, "title": title, "description": "spec", "role": "developer", "dependencies": dependencies or []}


def make_state(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    tasks = [Task(**definition("DONE"), status="completed"), Task(**definition("FAILED"), status="failed")]
    tasks[0].result = {"message": "original evidence"}
    tasks[1].error = "old failure"
    manager = TaskManager(tasks)
    plan = {"project": "demo", "summary": "baseline", "tasks": [definition("DONE"), definition("FAILED")]}
    ProjectPersistenceAdapter(source / "snapshots").save("demo-id", plan=plan, task_manager=manager, result=ProjectResult.from_task_manager(manager, project="demo"))
    metadata = {"project_id": "demo-id", "requirement": "original request", "workspace_root": str(tmp_path / "workspace"), "changes": [], "static_gate": True}
    (source / "project.json").write_text(json.dumps(metadata), encoding="utf-8")
    change = tmp_path / "change.md"
    change.write_text("revise failed work", encoding="utf-8")
    return source, change


def install_agents(monkeypatch, candidate=None):
    calls = []
    if candidate is None:
        candidate = {"project": "demo", "summary": "updated", "tasks": [definition("DONE"), definition("FAILED", title="revised", dependencies=["DONE"])]}

    class Planner:
        def run(self, task):
            assert "updated full specification" in task.context["requirement_analysis"]
            return {"plan": candidate}

    router = SimpleNamespace(get_agent=lambda role: {"planner": Planner(), "analyst": object()}.get(role))
    monkeypatch.setattr(main, "create_agent_router", lambda **kwargs: router)
    monkeypatch.setattr("runtime.change_request.run_quality_checked_analysis", lambda *a, **kw: SimpleNamespace(status="completed", message="updated full specification", data={"quality": {"ok": True}}))

    def execute(self, manager, *, state_change_hook):
        calls.append((self, manager))
        for task in manager.get_all_tasks():
            if task.status != "completed":
                manager.mark_ready(task.id)
                manager.mark_running(task.id)
                manager.mark_completed(task.id, {"message": "new evidence"})
                state_change_hook(manager)
        return ProjectResult.from_task_manager(manager, project="demo")

    monkeypatch.setattr(main.ProjectOrchestrator, "execute", execute)
    return calls


def test_failed_replan_keeps_completed_history_and_persists_new_graph(tmp_path, monkeypatch):
    source, change = make_state(tmp_path)
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*.json")}
    calls = install_agents(monkeypatch)
    destination = tmp_path / "next"
    _manager, result, _ = main.run_change_request(change_path=str(change), from_state=str(source), save_state=str(destination))
    assert result.success
    assert calls[0][0].static_gate is main.run_static_gate
    saved = ProjectPersistenceAdapter(destination / "snapshots").load("demo-id")
    assert saved.task_manager.get_task("DONE").result == {"message": "original evidence"}
    assert saved.task_manager.get_task("FAILED").status == "completed"
    assert saved.plan["tasks"][1]["title"] == "revised"
    metadata = json.loads((destination / "project.json").read_text(encoding="utf-8"))
    assert metadata["changes"][0]["modified_tasks"] == ["FAILED"]
    assert metadata["analysis"] == "updated full specification"
    assert before == {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*.json")}


def test_rejected_change_creates_no_destination(tmp_path, monkeypatch):
    source, change = make_state(tmp_path)
    calls = install_agents(monkeypatch, {"project": "demo", "summary": "invalid", "tasks": [definition("DONE", title="rewritten")]})
    destination = tmp_path / "next"
    with pytest.raises(ValueError, match="completed task"):
        main.run_change_request(change_path=str(change), from_state=str(source), save_state=str(destination))
    assert not destination.exists()
    assert not calls


def test_existing_destination_is_never_overwritten(tmp_path, monkeypatch):
    source, change = make_state(tmp_path)
    monkeypatch.setattr(main, "create_agent_router", lambda **kw: pytest.fail("must reject before provider setup"))
    before = (source / "project.json").read_bytes()
    with pytest.raises(FileExistsError):
        main.run_change_request(change_path=str(change), from_state=str(source), save_state=str(source))
    assert (source / "project.json").read_bytes() == before


def test_cli_change_uses_saved_requirement_and_json_output(tmp_path, monkeypatch, capsys):
    source, change = make_state(tmp_path)
    install_agents(monkeypatch)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--apply-change", str(change), "--from-state", str(source), "--save-state", str(tmp_path / "next"), "--output", "json"])
    assert main.main() == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["result"]["success"]


@pytest.mark.parametrize("options", [
    ["--apply-change", "change.md"],
    ["--from-state", "source", "requirement"],
    ["--apply-change", "c", "--from-state", "s", "--save-state", "d", "--projects-base", "other"],
    ["requirement", "--analyze-only", "--save-state", "d"],
])
def test_cli_rejects_incompatible_options(monkeypatch, options):
    monkeypatch.setattr(main.sys, "argv", ["main.py", *options])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


def test_initial_delivery_saves_reusable_state(tmp_path, monkeypatch):
    plan = {"project": "demo", "summary": "baseline", "tasks": [definition("NEW")]}
    install_agents(monkeypatch)

    def create_plan(self, requirement):
        self.last_plan = plan
        self.last_requirement_analysis = "baseline specification"
        return plan

    monkeypatch.setattr(main.ProjectOrchestrator, "create_plan", create_plan)
    destination = tmp_path / "initial"
    _, result, _ = main.run_project("initial requirement", projects_base=str(tmp_path / "workspace"), save_state=str(destination))
    assert result.success
    metadata = json.loads((destination / "project.json").read_text(encoding="utf-8"))
    snapshot = ProjectPersistenceAdapter(destination / "snapshots").load(metadata["project_id"])
    assert snapshot.result.success
    assert metadata["requirement"] == "initial requirement"
    assert metadata["analysis"] == "baseline specification"
