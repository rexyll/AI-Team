from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from runtime.scm_provider import SCMApprovalAuthority, SCMService


class FakeProvider:
    def __init__(self, *, ci="success", review="approved", draft=False, error=False):
        self.ci = ci
        self.review = review
        self.draft = draft
        self.error = error

    def get_pull_request(self, repository, pull_request_number):
        if self.error:
            raise RuntimeError("remote unavailable")
        return {
            "head_sha": "a" * 40,
            "state": "open",
            "merged": False,
            "draft": self.draft,
            "base_branch": "main",
        }

    def get_ci_status(self, repository, commit_sha):
        return {"status": self.ci}

    def get_review_status(self, repository, pull_request_number):
        return {"status": self.review}


def _orchestrator(provider):
    orchestrator = ProjectOrchestrator.__new__(ProjectOrchestrator)
    orchestrator.scm_service = SCMService(provider, SCMApprovalAuthority())
    orchestrator.scm_repository = "acme/widget"
    orchestrator.scm_pull_request_number = 17
    return orchestrator


def test_project_orchestrator_records_green_read_only_scm_observation():
    orchestrator = _orchestrator(FakeProvider())

    result = orchestrator._observe_scm_pull_request()

    assert result == {
        "status": "ready",
        "repository": "acme/widget",
        "pull_request_number": 17,
        "head_sha": "a" * 40,
        "pull_request_state": "open",
        "draft": False,
        "ci_status": "success",
        "review_status": "approved",
    }


def test_project_orchestrator_never_marks_non_green_scm_observation_ready():
    orchestrator = _orchestrator(FakeProvider(ci="pending", review="approved"))

    result = orchestrator._observe_scm_pull_request()

    assert result["status"] == "blocked"
    assert result["ci_status"] == "pending"


def test_project_orchestrator_blocks_draft_even_when_ci_and_review_are_green():
    orchestrator = _orchestrator(FakeProvider(draft=True))

    result = orchestrator._observe_scm_pull_request()

    assert result["status"] == "blocked"
    assert result["draft"] is True


def test_project_orchestrator_records_remote_failure_without_false_green():
    orchestrator = _orchestrator(FakeProvider(error=True))

    result = orchestrator._observe_scm_pull_request()

    assert result["status"] == "unavailable"
    assert result["error_type"] == "RuntimeError"
    assert "remote unavailable" not in str(result)


def test_project_orchestrator_skips_scm_observation_when_not_configured():
    orchestrator = ProjectOrchestrator.__new__(ProjectOrchestrator)
    orchestrator.scm_service = None

    assert orchestrator._observe_scm_pull_request() is None
