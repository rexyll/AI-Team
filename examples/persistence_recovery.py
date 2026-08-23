"""Persistence / recovery walkthrough on the canonical runtime contracts.

This example tells the full durable story of one small project:

1. Build canonical ``Task`` objects whose contexts embed their own tool
   execution history, exactly like the production Developer flow.
2. Persist an atomic project snapshot plus an immutable workflow event
   stream produced by the canonical task lifecycle.
3. Simulate a process crash/restart: every object below the restart line
   is created fresh and rehydrates from disk only.
4. Verify recovery parity, run cross-store event queries, and perform
   read-only tool-execution auditing over the recovered history.

Run from the repository root::

    python examples/persistence_recovery.py

The example writes only under its isolated run directory. All query and
audit construction after recovery is read-only.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Bootstrap repository-root imports so the file runs standalone
# (``python examples/persistence_recovery.py``) as well as via pytest.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.project_result import ProjectResult  # noqa: E402
from runtime.project_persistence import ProjectPersistenceAdapter  # noqa: E402
from runtime.task import Task  # noqa: E402
from runtime.task_manager import TaskManager  # noqa: E402
from runtime.tool_execution_record import ToolExecutionRecord  # noqa: E402
from runtime.workflow_event import WorkflowEvent  # noqa: E402
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter  # noqa: E402
from runtime.workflow_event_query import WorkflowEventQueryService  # noqa: E402


PROJECT_ID = "PROJECT-RECOVERY-001"

BASE_TIME = datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc)


def _stamp(seconds_offset: int) -> str:
    return (BASE_TIME + timedelta(seconds=seconds_offset)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# Canonical Developer-first lifecycle recorded by the real workflow runtime.
CANONICAL_TASK_LIFECYCLE = (
    "task_started",
    "developer_completed",
    "tester_skipped",
    "review_started",
    "reviewer_approved",
)

# Status-bearing events must carry their canonical task status in the
# payload, as validated by WorkflowEventProjector._validate_event().
_EVENT_PAYLOAD_STATUS = {
    "developer_completed": "completed",
    "reviewer_approved": "completed",
}


def _tool_record(
    index: int,
    task_id: str,
    tool_name: str,
    started_at: str,
    completed_at: str,
) -> dict:
    """Build one persistence-safe tool execution record owned by ``task_id``."""
    return ToolExecutionRecord(
        execution_id=f"TOOL-R{index:03d}",
        task_id=task_id,
        agent_role="developer",
        tool_name=tool_name,
        started_at=started_at,
        completed_at=completed_at,
        status="completed",
        arguments={"path": "src/module.py"},
        output={"written": True},
        metadata={"sandbox": "workspace"},
    ).to_dict()


def _build_tasks() -> list[Task]:
    specs = (
        ("TASK-R001", "implement expense parser", "parse_file"),
        ("TASK-R002", "write storage module", "write_file"),
    )
    tasks: list[Task] = []
    for index, (task_id, title, tool_name) in enumerate(specs, start=1):
        task = Task(
            id=task_id,
            title=title,
            description=f"Developer task: {title}",
            role="developer",
            status="completed",
            result={"summary": title},
        )
        task.context["tool_execution_history"] = [
            _tool_record(
                index,
                task_id,
                tool_name,
                started_at=_stamp(index * 60),
                completed_at=_stamp(index * 60 + 30),
            )
        ]
        tasks.append(task)
    return tasks


def _build_plan(tasks: list[Task]) -> dict:
    return {
        "project": PROJECT_ID,
        "tasks": [
            {"id": task.id, "title": task.title, "role": task.role}
            for task in tasks
        ],
    }


def _build_events(tasks: list[Task]) -> list[WorkflowEvent]:
    events: list[WorkflowEvent] = []
    counter = 0
    step = 0
    for task in tasks:
        for event_type in CANONICAL_TASK_LIFECYCLE:
            counter += 1
            step += 5
            payload = (
                {"status": _EVENT_PAYLOAD_STATUS[event_type]}
                if event_type in _EVENT_PAYLOAD_STATUS
                else {}
            )
            events.append(
                WorkflowEvent(
                    event_id=f"EVENT-R{counter:03d}",
                    event_type=event_type,
                    project_id=PROJECT_ID,
                    occurred_at=_stamp(step),
                    task_id=task.id,
                    payload=payload,
                )
            )
    return events


def run_example(root: str | Path | None = None) -> dict:
    base = Path(root) if root is not None else Path("./data/example-recovery")
    # Isolated run directory keeps repeated CLI invocations independent.
    run_dir = base / f"run-{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    # Phase 1 - execute and persist (before the simulated crash).
    # ------------------------------------------------------------------
    tasks = _build_tasks()
    task_manager = TaskManager(tasks)
    plan = _build_plan(tasks)
    result = ProjectResult.from_task_manager(task_manager, project=PROJECT_ID)

    project_store = ProjectPersistenceAdapter(run_dir / "projects")
    project_store.save(
        PROJECT_ID,
        plan=plan,
        task_manager=task_manager,
        result=result,
    )

    event_store = WorkflowEventPersistenceAdapter(run_dir / "events")
    for event in _build_events(tasks):
        event_store.save_if_absent(event)

    live_statuses = {
        task.id: task.status for task in task_manager.get_all_tasks()
    }

    # ------------------------------------------------------------------
    # Phase 2 - restart boundary. Everything below rehydrates from disk
    # through freshly constructed adapters; no in-memory state is shared
    # with Phase 1.
    # ------------------------------------------------------------------
    recovered_projects = ProjectPersistenceAdapter(run_dir / "projects")
    recovered_events = WorkflowEventPersistenceAdapter(run_dir / "events")

    snapshot = recovered_projects.load(PROJECT_ID)
    recovered_statuses = {
        task.id: task.status for task in snapshot.task_manager.get_all_tasks()
    }
    recovered_result = snapshot.result

    recovery = {
        "task_statuses_match": recovered_statuses == live_statuses,
        "result_total_tasks": recovered_result.total_tasks
        if recovered_result is not None
        else None,
        "result_completed_tasks": recovered_result.completed_tasks
        if recovered_result is not None
        else None,
        "result_success": recovered_result.success
        if recovered_result is not None
        else None,
    }
    recovery["equivalent"] = (
        recovery["task_statuses_match"]
        and recovery["result_total_tasks"] == len(tasks)
        and recovery["result_completed_tasks"] == len(tasks)
        and recovery["result_success"] is True
    )

    # Read-only operational query across the two independent stores.
    query = WorkflowEventQueryService.from_persisted_project(
        recovered_projects,
        recovered_events,
        project_id=PROJECT_ID,
    )

    # Read-only audit over the recovered tool execution history.
    audit = recovered_projects.audit(PROJECT_ID)
    consistency = recovered_projects.audit_consistency(PROJECT_ID)

    return {
        "project_id": PROJECT_ID,
        "run_dir": str(run_dir),
        "recovery": recovery,
        "recovered_task_statuses": recovered_statuses,
        "lifecycle": query.lifecycle(),
        "second_task_review_status": query.review_status("TASK-R002"),
        "last_event": query.last_event,
        "audit_summary": audit.summary(),
        "developer_record_count": len(audit.records(agent_role="developer")),
        "audit_consistency": {
            "consistent": consistency["consistent"],
            "canonical_count": consistency["canonical_count"],
        },
    }


if __name__ == "__main__":
    outcome = run_example()
    print(f"project              : {outcome['project_id']}")
    print(f"recovery equivalent  : {outcome['recovery']['equivalent']}")
    print(f"event lifecycle      : {outcome['lifecycle']}")
    print(f"TASK-R002 review     : {outcome['second_task_review_status']}")
    print(f"last event           : {outcome['last_event']}")
    print(f"audit summary        : {outcome['audit_summary']}")
    print(f"history consistency  : {outcome['audit_consistency']}")
