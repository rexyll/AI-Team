from copy import deepcopy
from types import SimpleNamespace

import pytest

from runtime.change_request import prepare_change
from runtime.project_persistence import ProjectSnapshot
from runtime.task import Task
from runtime.task_manager import TaskManager


def definition(task_id="OLD", **kwargs):
    return {"id": task_id, "title": kwargs.get("title", "original"), "description": "original specification", "role": "developer", "dependencies": kwargs.get("dependencies", [])}


def plan(*tasks):
    return {"project": "demo", "summary": "specification", "tasks": list(tasks)}


def snapshot(status="completed"):
    task = Task(**definition(), status=status)
    task.result = {"message": "old evidence"}
    task.context["tester_feedback"] = {"message": "old test"}
    return ProjectSnapshot("demo-id", plan(definition()), TaskManager([task]), None)


@pytest.fixture
def analysis(monkeypatch):
    calls = []

    def analyze(analyst, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", message="updated spec and impact", data={"quality": {"ok": True}})

    monkeypatch.setattr("runtime.change_request.run_quality_checked_analysis", analyze)
    return calls


def prepare(source, candidate):
    return prepare_change(source, requirement="original request", change="add export", analyst=object(), planner=lambda prompt, analysis: candidate)


def test_change_preserves_completed_history_and_only_new_work_is_pending(analysis):
    source = snapshot()
    before = source.task_manager.get_task("OLD").to_dict()
    proposal = prepare(source, plan(definition(), definition("NEW", dependencies=["OLD"])))
    assert proposal.task_manager.get_task("OLD").to_dict() == before
    assert proposal.task_manager.get_task("NEW").status == "pending"
    assert source.task_manager.get_all_tasks() == [source.task_manager.get_task("OLD")]
    assert proposal.record["added_tasks"] == ["NEW"]
    assert proposal.record["preserved_tasks"] == ["OLD"]
    assert analysis[0]["clarifications"] == "add export"
    assert "original request" in analysis[0]["requirement"]


@pytest.mark.parametrize("candidate", [
    plan(definition("NEW")),
    plan(definition(title="changed"), definition("NEW")),
    plan(definition(dependencies=["NEW"]), definition("NEW")),
    plan(definition()),
    plan(definition(), definition("NEW", dependencies=["MISSING"])),
    plan(definition(), definition("NEW", dependencies=["NEW"])),
    dict(plan(definition(), definition("NEW")), project="renamed"),
])
def test_invalid_candidate_does_not_mutate_source(analysis, candidate):
    source = snapshot()
    before = source.task_manager.get_task("OLD").to_dict()
    with pytest.raises(ValueError):
        prepare(source, candidate)
    assert source.task_manager.get_task("OLD").to_dict() == before


@pytest.mark.parametrize("status", ["ready", "running", "review_pending", "reviewing", "revision"])
def test_active_graph_rejected_before_analysis(analysis, status):
    with pytest.raises(RuntimeError, match="active"):
        prepare(snapshot(status), plan(definition(), definition("NEW")))
    assert analysis == []


@pytest.mark.parametrize("status", ["pending", "failed", "blocked"])
def test_unaffected_unfinished_tasks_keep_evidence(analysis, status):
    source = snapshot(status)
    proposal = prepare(source, plan(definition(), definition("NEW")))
    assert proposal.task_manager.get_task("OLD").to_dict() == source.task_manager.get_task("OLD").to_dict()


def test_changed_failed_work_resets_and_source_evidence_survives(analysis):
    source = snapshot("failed")
    proposal = prepare(source, plan(definition(title="implement revised request")))
    assert proposal.task_manager.get_task("OLD").status == "pending"
    assert proposal.record["modified_tasks"] == ["OLD"]
    assert source.task_manager.get_task("OLD").status == "failed"
    assert source.task_manager.get_task("OLD").result == {"message": "old evidence"}


def test_superseded_failed_task_is_explicit(analysis):
    proposal = prepare(snapshot("failed"), plan(definition("NEW")))
    assert proposal.record["superseded_tasks"] == ["OLD"]


def test_bad_analysis_never_calls_planner(monkeypatch):
    monkeypatch.setattr("runtime.change_request.run_quality_checked_analysis", lambda *a, **k: SimpleNamespace(status="completed", data={"quality": {"ok": False}}))
    with pytest.raises(ValueError, match="quality check"):
        prepare_change(snapshot(), requirement="r", change="c", analyst=object(), planner=lambda *a: pytest.fail("must not plan"))


@pytest.mark.parametrize("requirement,change", [("", "c"), ("r", "  "), (None, "c")])
def test_empty_input_rejected(analysis, requirement, change):
    with pytest.raises(ValueError, match="non-empty"):
        prepare_change(snapshot(), requirement=requirement, change=change, analyst=object(), planner=lambda *a: {})
    assert analysis == []


def test_planner_failure_does_not_mutate_source(analysis):
    source = snapshot()
    before = deepcopy(source.task_manager.get_task("OLD").to_dict())

    def fail(*args):
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider"):
        prepare_change(source, requirement="r", change="c", analyst=object(), planner=fail)
    assert source.task_manager.get_task("OLD").to_dict() == before
