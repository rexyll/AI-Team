from runtime.agent_result import AgentResult
from runtime.provenance import agent_feedback_provenance


def _ensure_stage_provenance(normalized: AgentResult) -> AgentResult:
    """Attach a canonical stage-feedback provenance to legacy gate results.

    Older agents and test doubles return the canonical AgentResult fields but
    do not yet carry explicit provenance.  The runtime normalization boundary
    is the trusted point where those results become workflow evidence.  Keep
    producer-supplied provenance untouched; only synthesize the missing stage
    feedback marker needed by the workflow evidence gate.
    """
    if normalized.agent not in {"tester", "reviewer"}:
        return normalized
    if not normalized.task_id:
        return normalized

    data = dict(normalized.data)
    if isinstance(data.get("provenance"), dict):
        return normalized

    if normalized.agent == "tester":
        evidence_id = f"tester:{normalized.task_id}"
        parent_evidence_id = f"developer:{normalized.task_id}"
    else:
        evidence_id = f"reviewer:{normalized.task_id}"
        parent_evidence_id = f"tester:{normalized.task_id}"

    data["provenance"] = agent_feedback_provenance(
        task_id=normalized.task_id,
        agent_role=normalized.agent,
        evidence_id=evidence_id,
        parent_evidence_id=parent_evidence_id,
    ).to_dict()
    return AgentResult(
        status=normalized.status,
        agent=normalized.agent,
        task_id=normalized.task_id,
        message=normalized.message,
        data=data,
    )


def normalize_agent_result(
    result,
    *,
    expected_agent: str | None = None,
    expected_task_id: str | None = None,
) -> AgentResult:
    """Normalize an Agent result and optionally validate its execution identity.

    ``expected_agent`` and ``expected_task_id`` are optional so existing
    callers keep their legacy behavior. Runtime orchestration code can provide
    them at stage boundaries to reject results produced for a different Agent
    or task.

    Tester and Reviewer results that do not yet carry explicit provenance are
    attested at this trusted normalization boundary so legacy agents remain
    compatible with the fail-closed workflow gate. Explicit provenance always
    wins and is never replaced.
    """
    if isinstance(result, AgentResult):
        normalized = result
    elif isinstance(result, dict):
        normalized = AgentResult.from_dict(result)
    else:
        raise TypeError(
            f"Unsupported agent result type: "
            f"{type(result).__name__}"
        )

    if expected_agent is not None:
        if not isinstance(expected_agent, str) or not expected_agent.strip():
            raise ValueError("expected_agent must be a non-empty string")
        expected_agent = expected_agent.strip()
        if normalized.agent != expected_agent:
            raise ValueError(
                "Agent result role mismatch: "
                f"expected '{expected_agent}', got '{normalized.agent}'"
            )

    if expected_task_id is not None:
        if not isinstance(expected_task_id, str) or not expected_task_id.strip():
            raise ValueError("expected_task_id must be a non-empty string")
        expected_task_id = expected_task_id.strip()
        if normalized.task_id != expected_task_id:
            raise ValueError(
                "Agent result task mismatch: "
                f"expected '{expected_task_id}', got '{normalized.task_id}'"
            )

    return _ensure_stage_provenance(normalized)
