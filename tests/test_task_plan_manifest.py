import json

import pytest

from runtime.task import Task
from runtime.task_plan_manifest import TaskPlanManifest, TaskPlanDriftError


def tasks():
    return [
        Task(id="TASK-001", title="实现核心", description="d", role="developer", dependencies=[]),
        Task(id="TASK-002", title="编写测试", description="d", role="developer", dependencies=["TASK-001"]),
        Task(id="TASK-003", title="最终审查", description="d", role="reviewer", dependencies=["TASK-002"]),
    ]


def manifest(tmp_path):
    return TaskPlanManifest(tmp_path, "proj-1")


def test_freeze_writes_json_and_markdown_with_roles(tmp_path):
    m = manifest(tmp_path)
    payload = m.freeze(tasks(), reason="initial plan freeze")
    assert payload["version"] == 1
    assert m.path.is_file()
    markdown = m.path.with_name("task_plan.md").read_text(encoding="utf-8")
    assert "任务计划清单" in markdown
    assert "| TASK-001 实现核心 | developer |" in markdown
    assert "| TASK-003 最终审查 | reviewer |" in markdown
    on_disk = json.loads(m.path.read_text(encoding="utf-8"))
    assert [entry["role"] for entry in on_disk["entries"]] == ["developer", "developer", "reviewer"]


def test_verify_accepts_unchanged_graph_and_records_dispatch(tmp_path):
    m = manifest(tmp_path)
    m.freeze(tasks(), reason="freeze")
    payload = m.verify(tasks())
    m.record_dispatch("TASK-001", 1)
    m.record_completion("TASK-001", "completed")
    on_disk = json.loads(m.path.read_text(encoding="utf-8"))
    entry = on_disk["entries"][0]
    assert entry["developer_slot"] == 1
    assert entry["status"] == "completed"
    assert m.verify(tasks())["plan_hash"] == payload["plan_hash"]


def test_verify_rejects_drifted_graph(tmp_path):
    m = manifest(tmp_path)
    m.freeze(tasks(), reason="freeze")
    drifted = [Task(id="TASK-001", title="实现核心", description="d", role="developer", dependencies=[]),
               Task(id="TASK-002", title="被篡改的任务", description="d", role="developer", dependencies=["TASK-001"])]
    with pytest.raises(TaskPlanDriftError, match="drifted"):
        m.verify(drifted)


def test_refreeze_with_changed_graph_bumps_version(tmp_path):
    m = manifest(tmp_path)
    m.freeze(tasks(), reason="freeze")
    m.record_dispatch("TASK-001", 0)
    drifted = [Task(id="TASK-001", title="实现核心", description="d", role="developer", dependencies=[]),
               Task(id="TASK-002", title="重规划后的任务", description="d", role="developer", dependencies=["TASK-001"])]
    payload = m.freeze(drifted, reason="recovery replan")
    assert payload["version"] == 2
    assert payload["reason"] == "recovery replan"
    assert m.verify(drifted)["version"] == 2


def test_refreeze_with_same_graph_keeps_dispatch_facts(tmp_path):
    m = manifest(tmp_path)
    m.freeze(tasks(), reason="freeze")
    m.record_dispatch("TASK-001", 1)
    payload = m.freeze(tasks(), reason="resume")
    assert payload["version"] == 1
    on_disk = json.loads(m.path.read_text(encoding="utf-8"))
    assert on_disk["entries"][0]["developer_slot"] == 1


def test_verify_without_manifest_raises(tmp_path):
    with pytest.raises(TaskPlanDriftError, match="no task plan manifest"):
        manifest(tmp_path).verify(tasks())
