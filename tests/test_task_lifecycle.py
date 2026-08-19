import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


def create_task(
    status: str = "pending",
) -> Task:
    return Task(
        id="TASK-001",
        title="Lifecycle test",
        description="Task lifecycle test",
        role="developer",
        status=status,
    )


def test_task_lifecycle_pending_to_ready_to_running():
    task = create_task()

    manager = TaskManager([task])

    manager.mark_ready(task.id)

    assert task.status == "ready"

    manager.mark_running(task.id)

    assert task.status == "running"


def test_task_lifecycle_records_status_history():
    task = create_task()

    manager = TaskManager([task])

    manager.mark_ready(task.id)
    manager.mark_running(task.id)

    assert task.status_history == [
        {
            "from": "pending",
            "to": "ready",
        },
        {
            "from": "ready",
            "to": "running",
        },
    ]


def test_developer_completion_enters_review_pending():
    task = create_task("running")

    manager = TaskManager([task])

    manager.mark_developer_completed(
        task.id,
        {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implementation complete",
        },
    )

    assert task.status == "review_pending"


def test_review_pending_to_reviewing():
    task = create_task("review_pending")

    manager = TaskManager([task])

    manager.mark_reviewing(task.id)

    assert task.status == "reviewing"


def test_review_approval_completes_task():
    task = create_task("reviewing")

    manager = TaskManager([task])

    review = {
        "status": "approved",
        "message": "LGTM",
    }

    manager.mark_review_approved(
        task.id,
        review,
    )

    assert task.status == "completed"
    assert task.review_result == review
    assert task.review_history == [review]
    assert task.review_round == 1


def test_review_revision_returns_to_running():
    task = create_task("reviewing")

    manager = TaskManager([task])

    review = {
        "status": "revision",
        "message": "Fix DAO transaction handling",
    }

    manager.mark_review_revision_required(
        task.id,
        review,
    )

    assert task.status == "running"
    assert task.review_result == review
    assert task.review_history == [review]
    assert task.review_round == 1
    assert task.context["reviewer_feedback"] == review


def test_tester_revision_returns_to_running():
    task = create_task("review_pending")

    manager = TaskManager([task])

    test_result = {
        "status": "failed",
        "message": "2 tests failed",
    }

    manager.mark_tester_revision_required(
        task.id,
        test_result,
    )

    assert task.status == "running"
    assert task.test_result == test_result
    assert task.context["tester_feedback"] == test_result


def test_running_to_completed_for_non_review_task():
    task = create_task("running")

    manager = TaskManager([task])

    result = {
        "status": "completed",
        "message": "done",
    }

    manager.mark_completed(
        task.id,
        result,
    )

    assert task.status == "completed"
    assert task.result == result


def test_running_to_failed():
    task = create_task("running")

    manager = TaskManager([task])

    manager.mark_failed(
        task.id,
        "execution failed",
    )

    assert task.status == "failed"
    assert task.error == "execution failed"


def test_invalid_transition_is_rejected():
    task = create_task("pending")

    manager = TaskManager([task])

    with pytest.raises(ValueError):
        manager.mark_completed(task.id)


def test_terminal_task_cannot_continue():
    task = create_task("completed")

    manager = TaskManager([task])

    with pytest.raises(ValueError):
        manager.mark_running(task.id)


def test_task_manager_terminal_state_helpers():
    completed = create_task("completed")
    failed = Task(
        id="TASK-002",
        title="failed",
        description="failed",
        role="developer",
        status="failed",
    )

    manager = TaskManager(
        [
            completed,
            failed,
        ]
    )

    assert manager.is_terminal(completed.id)
    assert manager.is_terminal(failed.id)

    assert not manager.is_active(completed.id)
    assert not manager.is_active(failed.id)
    
    
def test_record_test_result_updates_current_and_history():
    task = create_task("review_pending")

    manager = TaskManager([task])

    result = {
        "status": "passed",
        "message": "all tests passed",
    }

    manager.record_test_result(
        task.id,
        result,
    )

    assert task.test_result == result
    assert task.test_history == [result]
    
    
    
def test_record_test_result_preserves_test_history():
    task = create_task("review_pending")

    manager = TaskManager([task])

    result1 = {
        "status": "failed",
        "message": "test 1 failed",
    }

    result2 = {
        "status": "passed",
        "message": "all tests passed",
    }

    manager.record_test_result(
        task.id,
        result1,
    )

    manager.record_test_result(
        task.id,
        result2,
    )

    assert task.test_result == result2

    assert task.test_history == [
        result1,
        result2,
    ]
    
    
def test_record_review_result_updates_current_and_history():
    task = create_task("reviewing")

    manager = TaskManager([task])

    result = {
        "status": "approved",
        "message": "LGTM",
    }

    manager.record_review_result(
        task.id,
        result,
    )

    assert task.review_result == result
    assert task.review_history == [result]
    
def test_record_result():
    task = create_task("running")

    manager = TaskManager([task])

    result = {
        "status": "completed",
        "message": "implementation complete",
    }

    manager.record_result(
        task.id,
        result,
    )

    assert task.result == result
    
    
def test_record_agent_result():
    from runtime.agent_result import AgentResult

    task = create_task("running")

    manager = TaskManager([task])

    result = AgentResult(
        status="completed",
        agent="developer",
        task_id=task.id,
        message="done",
        data={
            "files": ["main.py"],
        },
    )

    manager.record_result(
        task.id,
        result,
    )

    assert task.result == result.to_dict()
    
    
def test_set_feedback():
    task = create_task("running")

    manager = TaskManager([task])

    feedback = {
        "message": "fix transaction handling",
    }

    manager.set_feedback(
        task.id,
        "reviewer",
        feedback,
    )

    assert task.context["reviewer_feedback"] == feedback
    
    
def test_record_error():
    task = create_task("running")

    manager = TaskManager([task])

    manager.record_error(
        task.id,
        "database connection failed",
    )

    assert task.error == "database connection failed"
    
    
def test_mark_completed_records_result():
    task = create_task("running")

    manager = TaskManager([task])

    result = {
        "status": "completed",
        "message": "done",
    }

    manager.mark_completed(
        task.id,
        result,
    )

    assert task.result == result
    
    
def test_review_revision_records_one_history_entry():
    task = create_task("reviewing")

    manager = TaskManager([task])

    review = {
        "status": "revision",
        "message": "fix DAO",
    }

    manager.mark_review_revision_required(
        task.id,
        review,
    )

    assert task.review_result == review
    assert task.review_history == [review]
    assert task.review_round == 1
    assert task.context["reviewer_feedback"] == review
    
def test_tester_revision_does_not_duplicate_test_history():
    task = create_task("review_pending")

    manager = TaskManager([task])

    test_result = {
        "status": "failed",
        "message": "DAO test failed",
    }

    manager.record_test_result(
        task.id,
        test_result,
    )

    manager.mark_tester_revision_required(
        task.id,
        test_result,
    )

    assert task.test_result == test_result
    assert task.test_history == [test_result]
    assert task.context["tester_feedback"] == test_result
    
    
def test_review_revision_returns_to_running():
    task = create_task("reviewing")

    manager = TaskManager([task])

    review = {
        "status": "revision",
        "message": "Fix DAO transaction handling",
    }

    manager.mark_review_revision_required(
        task.id,
        review,
    )

    assert task.status == "running"
    assert task.review_result == review
    assert task.review_history == [review]
    assert task.review_round == 1
    assert task.context["reviewer_feedback"] == review
    
    
def test_same_review_result_still_counts_as_new_round():
    task = create_task("reviewing")

    manager = TaskManager([task])

    review = {
        "status": "revision",
        "message": "REVISION_REQUIRED",
    }

    manager.record_review_result(
        task.id,
        review,
    )

    manager.record_review_result(
        task.id,
        review,
    )

    assert task.review_result == review
    assert task.review_history == [review, review]
    assert task.review_round == 2
    
    
