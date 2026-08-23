"""Release readiness smoke: the full real-agent pipeline, network-free.

This is the final Phase 8 gate. It drives real Planner / Architect /
Developer / Tester / Reviewer agents - each with a deterministic injected
``MockLLM`` - through ``ProjectOrchestrator``, persists the produced
workflow events durably, crosses a simulated restart boundary, and proves
recovery parity plus read-only cross-store querying and auditing of the
real tool execution history.
"""

from __future__ import annotations

import json

import pytest

import security.workspace as workspace_module
from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
# Aliased so pytest's ``Test*`` collection rule does not try to collect
# the agent class from this test module (mirrors test_agent_llm_injection).
from agents.tester import TesterAgent as RuntimeTesterAgent
from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.agent_router import AgentRouter
from runtime.llm.mock import MockLLM
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_query import WorkflowEventQueryService
from security.workspace import WorkspaceSandbox


PROJECT_ID = "PROJECT-RELEASE-SMOKE-001"
DEVELOPER_CALL_ID = "call-smoke-001"

PLAN = {
    "project": "note-keeper",
    "summary": "Minimal note-taking utility with one persisted module.",
    "tasks": [
        {
            "id": "TASK-001",
            "title": "design note module",
            "description": "Design the note-keeping module layout.",
            "role": "architect",
            "dependencies": [],
        },
        {
            "id": "TASK-002",
            "title": "implement note module",
            "description": "Implement notes.py inside the workspace.",
            "role": "developer",
            "dependencies": ["TASK-001"],
        },
    ],
}


def _build_router() -> AgentRouter:
    router = AgentRouter()
    router.register(PlannerAgent(llm=MockLLM(json.dumps(PLAN))))
    router.register(
        ArchitectAgent(
            llm=MockLLM(
                "Architecture: notes.py exposes add_note() and list_notes()."
            )
        )
    )
    router.register(
        DeveloperAgent(
            llm=MockLLM(
                "Implemented notes.py.",
                tool_script=[
                    {
                        "tool_calls": [
                            {
                                "call_id": DEVELOPER_CALL_ID,
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {"path": "notes.py", "content": "NOTES = []\n"}
                                ),
                            }
                        ]
                    }
                ],
            )
        )
    )
    router.register(
        RuntimeTesterAgent(
            llm=MockLLM("TEST_PASSED\nAll deterministic checks succeeded.")
        )
    )
    router.register(
        ReviewerAgent(llm=MockLLM("APPROVED\nImplementation satisfies the design."))
    )
    return router


def test_release_smoke_full_pipeline_without_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        workspace_module,
        "DEFAULT_SANDBOX",
        WorkspaceSandbox(tmp_path),
    )

    event_store = WorkflowEventPersistenceAdapter(tmp_path / "events")
    orchestrator = ProjectOrchestrator(
        agent_router=_build_router(),
        workflow_event_persistence=event_store,
        project_id=PROJECT_ID,
    )

    # Drive the canonical three-step project flow explicitly so the smoke
    # test holds the real plan, task manager, and result artifacts.
    # With the injected MockLLM, the planner parses the scripted JSON
    # verbatim after validation.
    plan = orchestrator.create_plan("Build a minimal note-taking utility")
    assert plan == PLAN
    task_manager = orchestrator.build_task_manager(plan)
    result = orchestrator.execute(task_manager)

    assert isinstance(result, ProjectResult)
    assert result.success is True

    tasks = task_manager.get_all_tasks()
    assert tasks, "orchestrator must produce tasks"
    assert all(task.status == "completed" for task in tasks)

    live_statuses = {task.id: task.status for task in tasks}

    # The real Developer tool call landed inside the sandboxed workspace.
    assert (tmp_path / "notes.py").read_text(encoding="utf-8") == "NOTES = []\n"

    # ------------------------------------------------------------------
    # Restart boundary: everything below rehydrates from disk through
    # freshly constructed adapters; no in-memory state is shared.
    # ------------------------------------------------------------------
    recovered_projects = ProjectPersistenceAdapter(tmp_path / "projects")
    recovered_events = WorkflowEventPersistenceAdapter(tmp_path / "events")

    recovered_projects.save(
        PROJECT_ID,
        plan=plan,
        task_manager=task_manager,
        result=result,
    )

    snapshot = recovered_projects.load(PROJECT_ID)
    assert {
        task.id: task.status for task in snapshot.task_manager.get_all_tasks()
    } == live_statuses
    assert snapshot.result == result

    query = WorkflowEventQueryService.from_persisted_project(
        recovered_projects,
        recovered_events,
        project_id=PROJECT_ID,
    )
    assert query.lifecycle() == "completed"

    # The Developer's real tool execution survives recovery and stays auditable.
    audit = recovered_projects.audit(PROJECT_ID)
    write_calls = audit.records(tool_name="write_file")
    assert [record.execution_id for record in write_calls] == [DEVELOPER_CALL_ID]
    summary = audit.summary()
    assert summary["total"] >= 1
    assert summary["by_tool"]["write_file"] == 1
    consistency = recovered_projects.audit_consistency(PROJECT_ID)
    assert consistency["consistent"] is True
