from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.context_builder import ContextBuilder
from runtime.evidence_lineage import collect_lineage
from runtime.provenance import agent_feedback_provenance, agent_result_provenance
from runtime.task import Task


def _task() -> Task:
    return Task(
        id="TASK-001",
        title="Implement feature",
        description="Implement and validate the feature.",
        role="developer",
    )


def _context(task: Task, role: str) -> AgentContext:
    return ContextBuilder().build_agent_context(task, role=role)


def test_developer_tester_reviewer_lineage_survives_context_boundaries() -> None:
    task = _task()
    developer = AgentResult(
        status="completed",
        agent="developer",
        task_id=task.id,
        data={"summary": "implemented"},
    )
    task.result = developer.to_dict()

    tester_context = _context(task, "tester")
    developer_provenance = agent_result_provenance(
        task_id=task.id,
        agent_role="developer",
    )
    tester = AgentResult(
        status="passed",
        agent="tester",
        task_id=task.id,
        data={
            "provenance": agent_feedback_provenance(
                task_id=task.id,
                agent_role="tester",
                evidence_id=f"tester:{task.id}",
                parent_evidence_id=developer_provenance.evidence_id,
            ).to_dict()
        },
    )
    task.test_result = tester.to_dict()

    reviewer_context = _context(task, "reviewer")
    reviewer = AgentResult(
        status="approved",
        agent="reviewer",
        task_id=task.id,
        data={
            "provenance": agent_feedback_provenance(
                task_id=task.id,
                agent_role="reviewer",
                evidence_id=f"reviewer:{task.id}:round:1",
                parent_evidence_id=f"tester:{task.id}",
            ).to_dict()
        },
    )

    assert tester_context.task_result == developer.to_dict()
    assert reviewer_context.tester_feedback == tester.to_dict()
    chain = collect_lineage(
        reviewer.data["provenance"],
        parents=(tester.data["provenance"], developer.to_dict()),
    )
    assert [item.evidence_id for item in chain] == [
        f"reviewer:{task.id}:round:1",
        f"tester:{task.id}",
        f"developer:{task.id}",
    ]


def test_revision_round_keeps_previous_evidence_as_explicit_parent() -> None:
    task = _task()
    task.review_round = 2
    previous_review = agent_feedback_provenance(
        task_id=task.id,
        agent_role="reviewer",
        evidence_id=f"reviewer:{task.id}:round:1",
        parent_evidence_id=f"tester:{task.id}",
    ).to_dict()
    task.review_result = {"provenance": previous_review}

    current_developer = AgentResult(
        status="completed",
        agent="developer",
        task_id=task.id,
        data={
            "provenance": agent_result_provenance(
                task_id=task.id,
                agent_role="developer",
                evidence_id=f"developer:{task.id}:round:2",
                parent_evidence_id=previous_review["evidence_id"],
            ).to_dict()
        },
    )
    task.result = current_developer.to_dict()

    current = current_developer.data["provenance"]
    chain = collect_lineage(current, parents=(previous_review,))
    assert [item.evidence_id for item in chain] == [
        f"developer:{task.id}:round:2",
        f"reviewer:{task.id}:round:1",
    ]


def test_context_builder_does_not_grant_visibility_from_lineage_reference() -> None:
    task = _task()
    task.result = {
        "status": "completed",
        "agent": "developer",
        "task_id": task.id,
        "data": {
            "provenance": agent_result_provenance(
                task_id=task.id,
                agent_role="developer",
            ).to_dict()
        },
    }

    context = _context(task, "tester")
    assert context.task_result == task.result
    assert "tool_execution_history" not in context.metadata
    assert "unrelated_evidence" not in context.metadata
