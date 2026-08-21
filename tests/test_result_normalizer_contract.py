import pytest

from runtime.agent_result import AgentResult
from runtime.result_normalizer import normalize_agent_result


def _result(**overrides):
    values = {
        "status": "completed",
        "agent": "developer",
        "task_id": "TASK-001",
        "message": "done",
    }
    values.update(overrides)
    return values


def test_normalizer_accepts_canonical_agent_result():
    result = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
    )

    assert normalize_agent_result(result) is result


def test_normalizer_validates_expected_agent():
    result = normalize_agent_result(
        _result(),
        expected_agent="developer",
    )

    assert result.agent == "developer"

    with pytest.raises(ValueError, match="role mismatch"):
        normalize_agent_result(
            _result(),
            expected_agent="reviewer",
        )


def test_normalizer_validates_expected_task_id():
    with pytest.raises(ValueError, match="task mismatch"):
        normalize_agent_result(
            _result(),
            expected_task_id="TASK-999",
        )


def test_normalizer_keeps_legacy_one_argument_behavior():
    result = normalize_agent_result(
        {
            "status": "completed",
            "agent": "developer",
            "task_id": "TASK-001",
        }
    )

    assert result.status == "completed"
    assert result.agent == "developer"
    assert result.task_id == "TASK-001"


def test_normalizer_rejects_invalid_expected_identity():
    with pytest.raises(ValueError, match="expected_agent"):
        normalize_agent_result(_result(), expected_agent=" ")

    with pytest.raises(ValueError, match="expected_task_id"):
        normalize_agent_result(_result(), expected_task_id=" ")
