import json
import logging

import pytest

from runtime.structured_logging import StructuredLogger, build_log_record


def test_build_log_record_has_canonical_envelope_and_redacts_secrets():
    record = build_log_record(
        "workflow.stage.completed",
        level="warning",
        fields={"task_id": "TASK-001", "api_key": "secret", "message": "spoof"},
    )

    assert record["level"] == "WARNING"
    assert record["event"] == "workflow.stage.completed"
    assert record["fields"]["task_id"] == "TASK-001"
    assert record["fields"]["api_key"] == "[REDACTED]"
    assert record["fields"]["message"] == "spoof"
    assert "timestamp" in record
    json.dumps(record, ensure_ascii=False)


def test_structured_logger_emits_json(caplog):
    logger = logging.getLogger("test.ai_team")
    adapter = StructuredLogger(logger)

    with caplog.at_level(logging.INFO, logger="test.ai_team"):
        adapter.info("task.completed", fields={"task_id": "TASK-001"})

    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "task.completed"
    assert payload["fields"]["task_id"] == "TASK-001"


def test_build_log_record_rejects_invalid_event_and_non_json_fields():
    with pytest.raises(ValueError):
        build_log_record("")
    with pytest.raises(TypeError):
        build_log_record("bad", fields={"value": object()})
