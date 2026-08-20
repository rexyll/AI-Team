import pytest

from runtime.agent_context import AgentContext
from runtime.context_builder import ContextBuilder
from runtime.task import Task
from runtime.task_manager import TaskManager


def make_task(**overrides):
    values = {
        "id": "TASK-001",
        "title": "History contract",
        "description": "Validate execution history context",
        "role": "developer",
        "status": "running",
    }
    values.update(overrides)
    return Task(**values)


def test_context_builder_exposes_lifecycle_history_as_history():
    task = make_task(
        status_history=[
            {"from": "pending", "to": "ready"},
            {"from": "ready", "to": "running"},
        ]
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.history == [
        {"from": "pending", "to": "ready"},
        {"from": "ready", "to": "running"},
    ]


def test_context_builder_exposes_test_history_separately():
    task = make_task(
        test_result={
            "status": "passed",
            "message": "all tests passed",
        },
        test_history=[
            {"status": "failed", "message": "first run failed"},
            {"status": "passed", "message": "all tests passed"},
        ],
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.tester_feedback == task.test_result
    assert context.test_history == [
        {"status": "failed", "message": "first run failed"},
        {"status": "passed", "message": "all tests passed"},
    ]


def test_context_builder_exposes_review_history_separately():
    task = make_task(
        review_round=2,
        review_result={
            "status": "revision",
            "message": "fix transaction handling",
        },
        review_history=[
            {"status": "revision", "message": "fix transaction handling"},
            {"status": "approved", "message": "LGTM"},
        ],
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.reviewer_feedback == task.review_result
    assert context.review_history == [
        {"status": "revision", "message": "fix transaction handling"},
        {"status": "approved", "message": "LGTM"},
    ]
    assert context.review_round == 2


def test_context_history_isolated_from_task_history():
    task = make_task(
        status_history=[{"from": "pending", "to": "ready"}],
        test_history=[{"status": "failed"}],
        review_history=[{"status": "revision"}],
    )

    context = ContextBuilder({}).build_agent_context(task)

    task.status_history[0]["to"] = "running"
    task.test_history[0]["status"] = "passed"
    task.review_history[0]["status"] = "approved"

    assert context.history == [{"from": "pending", "to": "ready"}]
    assert context.test_history == [{"status": "failed"}]
    assert context.review_history == [{"status": "revision"}]


def test_context_history_isolated_when_context_is_modified():
    task = make_task(
        status_history=[{"from": "pending", "to": "ready"}],
        test_history=[{"status": "failed", "details": {"count": 2}}],
        review_history=[{"status": "revision", "details": {"round": 1}}],
    )

    context = ContextBuilder({}).build_agent_context(task)

    context.history[0]["to"] = "running"
    context.test_history[0]["details"]["count"] = 0
    context.review_history[0]["details"]["round"] = 99

    assert task.status_history == [{"from": "pending", "to": "ready"}]
    assert task.test_history == [
        {"status": "failed", "details": {"count": 2}}
    ]
    assert task.review_history == [
        {"status": "revision", "details": {"round": 1}}
    ]


def test_history_round_trip_preserves_all_history_streams():
    context = AgentContext(
        task_id="TASK-001",
        task_title="History contract",
        task_description="Validate execution history context",
        role="developer",
        status="running",
        review_round=2,
        history=[{"from": "ready", "to": "running"}],
        test_history=[
            {"status": "failed"},
            {"status": "passed"},
        ],
        review_history=[
            {"status": "revision"},
            {"status": "approved"},
        ],
    )

    restored = AgentContext.from_dict(context.to_dict())

    assert restored.history == context.history
    assert restored.test_history == context.test_history
    assert restored.review_history == context.review_history


def test_context_history_is_not_duplicated_by_feedback_fields():
    task = make_task(
        test_result={"status": "passed"},
        test_history=[{"status": "failed"}, {"status": "passed"}],
        review_result={"status": "approved"},
        review_history=[{"status": "revision"}, {"status": "approved"}],
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.tester_feedback == {"status": "passed"}
    assert context.test_history == [
        {"status": "failed"},
        {"status": "passed"},
    ]
    assert context.reviewer_feedback == {"status": "approved"}
    assert context.review_history == [
        {"status": "revision"},
        {"status": "approved"},
    ]


def test_revision_flow_preserves_test_and_review_history():
    task = make_task(status="reviewing")
    manager = TaskManager([task])

    manager.record_test_result(
        task.id,
        {"status": "failed", "message": "first test run failed"},
    )
    manager.mark_tester_revision_required(
        task.id,
        {"status": "failed", "message": "first test run failed"},
    )

    manager.mark_reviewing(task.id) if task.status == "review_pending" else None

    # Simulate the next successful test and reviewer revision cycle using
    # the existing TaskManager history contracts.
    manager.record_test_result(
        task.id,
        {"status": "passed", "message": "second test run passed"},
    )
    task.status = "reviewing"
    manager.record_review_result(
        task.id,
        {"status": "revision", "message": "needs one more fix"},
    )

    context = ContextBuilder({task.id: task}).build_agent_context(task)

    assert len(context.test_history) == 2
    assert context.test_history[0]["status"] == "failed"
    assert context.test_history[1]["status"] == "passed"
    assert len(context.review_history) == 1
    assert context.review_history[0]["status"] == "revision"


def test_agent_context_validates_history_stream_types():
    with pytest.raises(ValueError, match="test_history"):
        AgentContext(
            task_id="TASK-001",
            task_title="History contract",
            task_description="Validate history",
            role="developer",
            status="running",
            test_history={},
        )

    with pytest.raises(ValueError, match="review_history"):
        AgentContext(
            task_id="TASK-001",
            task_title="History contract",
            task_description="Validate history",
            role="developer",
            status="running",
            review_history={},
        )
