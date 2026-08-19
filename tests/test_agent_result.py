import pytest

from runtime.agent_result import AgentResult


def test_agent_result_creation():
    result = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
        message="Implementation completed",
    )

    assert result.status == "completed"
    assert result.agent == "developer"
    assert result.task_id == "TASK-001"
    assert result.message == "Implementation completed"
    assert result.data == {}


def test_agent_result_supports_data():
    result = AgentResult(
        status="passed",
        agent="tester",
        task_id="TASK-001",
        message="All tests passed",
        data={
            "passed": 10,
            "failed": 0,
        },
    )

    assert result.data["passed"] == 10
    assert result.data["failed"] == 0


def test_agent_result_to_dict():
    result = AgentResult(
        status="approved",
        agent="reviewer",
        task_id="TASK-001",
        message="APPROVED",
        data={
            "round": 1,
        },
    )

    assert result.to_dict() == {
        "status": "approved",
        "agent": "reviewer",
        "task_id": "TASK-001",
        "message": "APPROVED",
        "data": {
            "round": 1,
        },
    }


def test_agent_result_from_dict():
    result = AgentResult.from_dict(
        {
            "status": "revision",
            "agent": "reviewer",
            "task_id": "TASK-001",
            "message": "REVISION_REQUIRED",
            "data": {
                "round": 1,
            },
        }
    )

    assert result.status == "revision"
    assert result.agent == "reviewer"
    assert result.task_id == "TASK-001"
    assert result.message == "REVISION_REQUIRED"
    assert result.data == {
        "round": 1,
    }


def test_agent_result_round_trip():
    original = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
        message="done",
        data={
            "files": [
                "main.py",
                "test_main.py",
            ]
        },
    )

    restored = AgentResult.from_dict(
        original.to_dict()
    )

    assert restored == original


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "agent",
        "task_id",
    ],
)
def test_agent_result_requires_core_fields(field):
    values = {
        "status": "completed",
        "agent": "developer",
        "task_id": "TASK-001",
    }

    values[field] = ""

    with pytest.raises(ValueError):
        AgentResult(**values)


def test_agent_result_requires_string_message():
    with pytest.raises(
        ValueError,
        match="message must be a string",
    ):
        AgentResult(
            status="completed",
            agent="developer",
            task_id="TASK-001",
            message=123,
        )


def test_agent_result_requires_dictionary_data():
    with pytest.raises(
        ValueError,
        match="data must be a dictionary",
    ):
        AgentResult(
            status="completed",
            agent="developer",
            task_id="TASK-001",
            data=[],
        )


def test_agent_result_from_dict_requires_dictionary():
    with pytest.raises(
        ValueError,
        match="input must be a dictionary",
    ):
        AgentResult.from_dict([])


def test_agent_result_from_dict_requires_core_fields():
    with pytest.raises(
        ValueError,
        match="missing required fields",
    ):
        AgentResult.from_dict(
            {
                "status": "completed",
            }
        )


def test_agent_result_defaults_optional_fields():
    result = AgentResult.from_dict(
        {
            "status": "completed",
            "agent": "developer",
            "task_id": "TASK-001",
        }
    )

    assert result.message == ""
    assert result.data == {}
    
    
def test_agent_result_supports_legacy_dict_access():
    result = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
        message="done",
    )


def test_agent_result_supports_legacy_get():
    result = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
        message="done",
    )

def test_agent_result_rejects_unknown_legacy_key():
    result = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
    )

    with pytest.raises(KeyError):
        _ = result["unknown"]
        
def test_agent_result_normalizes_legacy_status():
    result = AgentResult(
        status="architect_completed",
        agent="architect",
        task_id="TASK-001",
    )

    assert result.status == "completed"
    
    
def test_agent_result_preserves_legacy_architecture_payload():
    result = AgentResult.from_dict(
        {
            "status": "architect_completed",
            "agent": "architect",
            "task_id": "TASK-001",
            "architecture": "SQLite schema design",
        }
    )

    assert result.status == "completed"

    assert result.data == {
        "architecture": "SQLite schema design",
    }
    
    
def test_agent_result_preserves_multiple_legacy_fields():
    result = AgentResult.from_dict(
        {
            "status": "architect_completed",
            "agent": "architect",
            "task_id": "TASK-001",
            "architecture": "SQLite",
            "risk": "REAL precision",
            "decision": "Use INTEGER cents",
        }
    )

    assert result.data == {
        "architecture": "SQLite",
        "risk": "REAL precision",
        "decision": "Use INTEGER cents",
    }
    
    
def test_agent_result_preserves_existing_data():
    result = AgentResult.from_dict(
        {
            "status": "completed",
            "agent": "developer",
            "task_id": "TASK-001",
            "data": {
                "files": [
                    "main.py",
                ]
            },
            "files": [
                "legacy.py",
            ],
        }
    )

    assert result.data == {
        "files": [
            "main.py",
        ]
    }
    
    
@pytest.mark.parametrize(
    "legacy_status, expected_status",
    [
        ("architect_completed", "completed"),
        ("developer_completed", "completed"),
        ("tester_passed", "passed"),
        ("tester_failed", "failed"),
        ("reviewer_approved", "approved"),
        ("reviewer_revision", "revision"),
    ],
)
def test_agent_result_normalizes_legacy_statuses(
    legacy_status,
    expected_status,
):
    result = AgentResult(
        status=legacy_status,
        agent="test-agent",
        task_id="TASK-001",
    )

    assert result.status == expected_status
    
    
def test_normalize_result_status_preserves_unknown_status():
    from runtime.agent_result import normalize_result_status

    assert (
        normalize_result_status("custom_status")
        == "custom_status"
    )
    
    
def test_normalize_result_status_rejects_empty_status():
    from runtime.agent_result import normalize_result_status

    with pytest.raises(ValueError):
        normalize_result_status("")
