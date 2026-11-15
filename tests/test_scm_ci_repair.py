from __future__ import annotations

import pytest

from runtime.scm_ci_repair import SCMCIRepairError, SCMCIRepairTaskFactory
from runtime.scm_provider import SCMApprovalAuthority, SCMService
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


class FakeProvider:
    def __init__(self, *, ci="failure", state="open", merged=False):
        self.ci = ci
        self.state = state
        self.merged = merged
        self.head = "a" * 40
        self.check_runs = [
            {
                "id": 17,
                "name": "unit tests",
                "status": "completed",
                "conclusion": "failure",
                "head_sha": self.head,
                "started_at": "2026-11-15T10:00:00Z",
                "completed_at": "2026-11-15T10:01:00Z",
                "output": {"summary": "not retained in task evidence"},
            }
        ]
        self.calls = []

    def get_pull_request(self, repository, pull_request_number):
        self.calls.append(("pull_request", repository, pull_request_number))
        return {"head_sha": self.head, "state": self.state, "merged": self.merged}

    def get_ci_status(self, repository, commit_sha):
        self.calls.append(("ci", repository, commit_sha))
        return {
            "status": self.ci,
            "commit_status": "failure",
            "check_runs": self.check_runs,
        }


def _setup(**kwargs):
    provider = FakeProvider(**kwargs)
    service = SCMService(provider, SCMApprovalAuthority())
    manager = TaskManager(
        [
            Task(
                id="WORK-001",
                title="Implement feature",
                description="original implementation",
                role="developer",
                status=TaskStatus.COMPLETED.value,
            )
        ]
    )
    return SCMCIRepairTaskFactory(max_repair_rounds=2), service, provider, manager


def test_ci_failure_creates_blocked_host_approval_task_with_original_status_evidence():
    factory, service, provider, manager = _setup()
    proposal = factory.propose(
        service, manager, repository="acme/widget", pull_request_number=17
    )

    assert proposal.status == "proposed"
    assert proposal.round == 1
    assert proposal.task is not None
    assert proposal.task.status == TaskStatus.BLOCKED.value
    metadata = proposal.task.context["scm_ci_repair"]
    evidence = metadata["original_status_evidence"]
    assert evidence["pull_request"]["head_sha"] == provider.head
    assert evidence["ci"]["status"] == "failure"
    assert evidence["ci"]["commit_status"] == "failure"
    assert evidence["ci"]["check_runs"] == [
        {
            "id": 17,
            "name": "unit tests",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": provider.head,
            "started_at": "2026-11-15T10:00:00Z",
            "completed_at": "2026-11-15T10:01:00Z",
        }
    ]
    assert "output" not in str(evidence)
    assert metadata["requires_host_approval"] is True
    assert metadata["proposal_status"] == "awaiting_host_approval"
    assert metadata["evidence_sha256"] == proposal.evidence_sha256
    assert metadata["agent_evidence"].startswith('<untrusted-data source="github.ci_status_evidence">')
    manager.add_blocked_task(proposal.task)
    assert manager.get_ready_tasks() == []
    assert manager.get_task(proposal.task.id).status == TaskStatus.BLOCKED.value


def test_identical_ci_evidence_is_idempotent_and_does_not_create_second_task():
    factory, service, _, manager = _setup()
    first = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)
    manager.add_blocked_task(first.task)

    second = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)

    assert second.status == "duplicate"
    assert second.task is first.task
    assert len(manager.get_all_tasks()) == 2


@pytest.mark.parametrize(
    ("ci", "state", "merged", "expected_reason"),
    [
        ("pending", "open", False, "CI status is not failure"),
        ("success", "open", False, "CI status is not failure"),
        ("unknown", "open", False, "CI status is not failure"),
        ("failure", "closed", False, "pull request is not open and unmerged"),
        ("failure", "open", True, "pull request is not open and unmerged"),
    ],
)
def test_non_failure_or_non_open_pr_never_creates_a_repair_task(
    ci, state, merged, expected_reason
):
    factory, service, _, manager = _setup(ci=ci, state=state, merged=merged)

    proposal = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)

    assert proposal.status == "not_eligible"
    assert proposal.task is None
    assert proposal.reason == expected_reason
    assert len(manager.get_all_tasks()) == 1


def test_outstanding_repair_task_blocks_a_second_proposal_for_the_same_pr():
    factory, service, provider, manager = _setup()
    first = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)
    manager.add_blocked_task(first.task)
    provider.head = "b" * 40

    second = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)

    assert second.status == "awaiting_previous_repair"
    assert second.task is first.task
    assert len(manager.get_all_tasks()) == 2


def _complete_blocked_task(manager, task_id):
    manager.mark_ready(task_id)
    manager.mark_running(task_id)
    manager.mark_completed(task_id, {"status": "completed"})


def test_repair_rounds_are_bounded_per_pr_across_new_head_shas():
    factory, service, provider, manager = _setup()
    first = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)
    manager.add_blocked_task(first.task)
    _complete_blocked_task(manager, first.task.id)

    provider.head = "b" * 40
    second = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)
    assert second.status == "proposed"
    assert second.round == 2
    manager.add_blocked_task(second.task)
    _complete_blocked_task(manager, second.task.id)

    provider.head = "c" * 40
    third = factory.propose(service, manager, repository="acme/widget", pull_request_number=17)

    assert third.status == "round_limit_reached"
    assert third.task is None
    assert len(manager.get_all_tasks()) == 3


def test_malformed_ci_check_run_payload_fails_closed():
    factory, service, provider, manager = _setup()
    provider.check_runs = [{"id": 1}, "unexpected-string"]

    with pytest.raises(SCMCIRepairError, match="check run entry"):
        factory.propose(service, manager, repository="acme/widget", pull_request_number=17)


def test_factory_rejects_unbounded_round_configuration_and_invalid_identity():
    with pytest.raises(ValueError, match="max_repair_rounds"):
        SCMCIRepairTaskFactory(max_repair_rounds=100)
    factory, service, _, manager = _setup()
    with pytest.raises(ValueError, match="path is invalid"):
        factory.propose(service, manager, repository="../widget", pull_request_number=17)
    with pytest.raises(ValueError, match="positive integer"):
        factory.propose(service, manager, repository="acme/widget", pull_request_number=True)


def test_task_manager_accepts_only_blocked_tasks_and_rejects_duplicate_ids():
    manager = TaskManager([])
    blocked = Task(
        id="PROPOSAL-1",
        title="Proposal",
        description="Await host approval",
        role="developer",
        status=TaskStatus.BLOCKED.value,
    )
    manager.add_blocked_task(blocked)
    with pytest.raises(ValueError, match="Duplicate task id"):
        manager.add_blocked_task(blocked)

    pending = Task(
        id="PROPOSAL-2",
        title="Proposal",
        description="Not blocked",
        role="developer",
    )
    with pytest.raises(ValueError, match="start blocked"):
        manager.add_blocked_task(pending)


def test_project_orchestrator_registers_proposal_in_task_graph_and_plan():
    from core.project_orchestrator import ProjectOrchestrator

    _, service, _, manager = _setup()
    orchestrator = ProjectOrchestrator.__new__(ProjectOrchestrator)
    orchestrator.scm_service = service
    orchestrator.scm_repository = "acme/widget"
    orchestrator.scm_pull_request_number = 17
    orchestrator.last_scm_observation = {"ci_status": "failure"}
    orchestrator.last_scm_repair_proposal = None
    orchestrator.last_plan = {
        "project": "fixture",
        "summary": "Existing project plan",
        "tasks": [
            {
                "id": "WORK-001",
                "title": "Implement feature",
                "description": "original implementation",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }
    orchestrator._emit_project_event = lambda *args, **kwargs: None

    result = orchestrator._propose_scm_ci_repair_task(manager)

    assert result["status"] == "proposed"
    assert len(manager.get_all_tasks()) == 2
    assert manager.get_task(result["task_id"]).status == TaskStatus.BLOCKED.value
    assert orchestrator.last_plan["tasks"][-1]["id"] == result["task_id"]
    assert manager.get_ready_tasks() == []
