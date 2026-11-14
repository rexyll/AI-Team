"""Security audit, release gate and deployment readiness workflow contracts.

These cover the standard-flow gaps closed by the governance roles: a
deterministic security audit after QA, a release go/no-go gate before any
release, and a deployment-readiness review after monitoring. Deterministic
verdicts must stay reproducible without an LLM, and an agent may never waive
a deterministic blocker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.governance import ReleaseManagerAgent, SREAgent, SecurityEngineerAgent
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter
from runtime.deployment_readiness import run_deployment_readiness
from runtime.llm.base import BaseLLM
from runtime.release_gate import evaluate_release_gate
from runtime.security_audit import run_security_audit, write_security_report


class _StaticLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("governance agents must not use tools")


def _security_agent(text: str) -> SecurityEngineerAgent:
    return SecurityEngineerAgent(
        AgentConfig(role="security", model="security-model"),
        llm=_StaticLLM(text),
    )


def _sre_agent(text: str) -> SREAgent:
    return SREAgent(AgentConfig(role="sre", model="sre-model"), llm=_StaticLLM(text))


def _release_manager(text: str) -> ReleaseManagerAgent:
    return ReleaseManagerAgent(
        AgentConfig(role="release_manager", model="release-model"),
        llm=_StaticLLM(text),
    )


def _clean_deliverable(root: Path) -> None:
    """Build a deliverable that satisfies every deployment-readiness check."""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "deployment.md").write_text(
        "# 部署指引\n\n## 安装\npip install -r requirements.txt\n\n"
        "## 启动\npython main.py\n\n## 回退\ngit revert <version>\n",
        encoding="utf-8",
    )
    for name in ("requirements.md", "design.md", "test_report.md", "user_manual.md"):
        (docs / name).write_text(f"# {name}\n", encoding="utf-8")
    monitoring = root / "monitoring"
    monitoring.mkdir(exist_ok=True)
    (monitoring / "health_contract.json").write_text(
        json.dumps({"probes": ["manifest_integrity", "regression_suite"]}),
        encoding="utf-8",
    )
    (root / "MONITORING.md").write_text("# 监控运行手册\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Deterministic security audit
# ---------------------------------------------------------------------------


def test_security_audit_fails_on_high_severity_and_masks_secret(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8"
    )

    audit = run_security_audit(tmp_path)

    assert audit["status"] == "completed"
    assert audit["verdict"] == "SEC_FAILED"
    assert audit["high_severity"] >= 1
    assert audit["files_scanned"] >= 1

    report = write_security_report(tmp_path, audit)
    text = report.read_text(encoding="utf-8")
    assert "SEC_FAILED" in text
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "***" in text


def test_security_audit_flags_dangerous_construct(tmp_path: Path):
    (tmp_path / "runner.py").write_text(
        "import subprocess\nsubprocess.run(cmd, shell=True)\n", encoding="utf-8"
    )

    audit = run_security_audit(tmp_path)

    assert audit["verdict"] == "SEC_FAILED"
    assert {item["rule"] for item in audit["findings"]} >= {"shell_execution"}


def test_security_audit_passes_clean_deliverable(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")

    audit = run_security_audit(tmp_path)

    assert audit["verdict"] == "SEC_PASSED"
    assert audit["high_severity"] == 0
    assert audit["findings"] == []


def test_security_audit_skips_missing_root(tmp_path: Path):
    audit = run_security_audit(tmp_path / "missing")

    assert audit["status"] == "skipped"
    assert audit["verdict"] == "SEC_SKIPPED"


# ---------------------------------------------------------------------------
# Deterministic deployment readiness
# ---------------------------------------------------------------------------


def test_deployment_readiness_ready_with_complete_evidence(tmp_path: Path):
    _clean_deliverable(tmp_path)

    readiness = run_deployment_readiness(tmp_path)

    assert readiness["verdict"] == "SRE_READY"
    assert readiness["failed_checks"] == []
    assert readiness["limitation"]


def test_deployment_readiness_degrades_without_deployment_guide(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text("# 需求\n", encoding="utf-8")

    readiness = run_deployment_readiness(tmp_path)

    assert readiness["verdict"] == "SRE_DEGRADED"
    assert "deployment_guide" in readiness["failed_checks"]
    assert "handover_documents" in readiness["failed_checks"]


def test_deployment_readiness_requires_release_notes_for_released_version(tmp_path: Path):
    _clean_deliverable(tmp_path)
    release = {"status": "released", "version": "1.0.0"}

    missing = run_deployment_readiness(tmp_path, release=release)
    assert "release_notes" in missing["failed_checks"]

    (tmp_path / "RELEASE_NOTES.md").write_text("# 1.0.0\n", encoding="utf-8")
    recorded = run_deployment_readiness(tmp_path, release=release)
    assert recorded["verdict"] == "SRE_READY"


# ---------------------------------------------------------------------------
# Deterministic release gate
# ---------------------------------------------------------------------------


def test_release_gate_allows_when_evidence_is_green():
    gate = evaluate_release_gate(
        integration={"status": "passed"},
        qa={"verdict": "QA_PASSED"},
        security={"verdict": "SEC_PASSED"},
    )

    assert gate == {"status": "allowed", "blockers": []}


@pytest.mark.parametrize(
    ("evidence", "code"),
    [
        ({"integration": {"status": "failed"}}, "integration_failed"),
        ({"qa": {"verdict": "QA_FAILED"}}, "qa_failed"),
        ({"security": {"verdict": "SEC_FAILED"}}, "security_failed"),
    ],
)
def test_release_gate_blocks_each_deterministic_failure(evidence, code):
    gate = evaluate_release_gate(**evidence)

    assert gate["status"] == "blocked"
    assert [blocker["code"] for blocker in gate["blockers"]] == [code]


# ---------------------------------------------------------------------------
# Orchestrator phases
# ---------------------------------------------------------------------------


def test_security_phase_cannot_waive_deterministic_failure(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        'token = "sk-' + "a" * 40 + '"\n', encoding="utf-8"
    )
    router = AgentRouter()
    router.register("security", _security_agent("SEC_PASSED\n误报，可忽略。"))

    security = ProjectOrchestrator(agent_router=router)._run_security_phase(tmp_path)

    assert security["verdict"] == "SEC_FAILED"
    assert security["review"]["verdict"] == "SEC_PASSED"
    assert (tmp_path / "docs" / "security_audit.md").is_file()


def test_security_phase_accepts_agent_escalation_on_clean_deliverable(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    router = AgentRouter()
    router.register("security", _security_agent("SEC_FAILED\n发现可疑依赖声明。"))

    security = ProjectOrchestrator(agent_router=router)._run_security_phase(tmp_path)

    assert security["verdict"] == "SEC_FAILED"
    assert security["high_severity"] == 0


def test_release_gate_phase_blocks_qa_failure_without_release_manager():
    orchestrator = ProjectOrchestrator(agent_router=AgentRouter())

    record = orchestrator._run_release_gate_phase(
        integration={"status": "passed"},
        qa={"verdict": "QA_FAILED"},
        security={"verdict": "SEC_PASSED"},
        acceptance={"verdict": "passed"},
    )

    assert record["status"] == "blocked"
    assert record["blocking_code"] == "qa_failed"
    assert record["reason"] == "QA verdict is QA_FAILED"
    assert record["manager"] is None


def test_release_gate_phase_honours_release_manager_go():
    router = AgentRouter()
    router.register("release_manager", _release_manager("RELEASE_GO\n证据齐全。"))

    record = ProjectOrchestrator(agent_router=router)._run_release_gate_phase(
        integration={"status": "passed"},
        qa={"verdict": "QA_PASSED"},
        security={"verdict": "SEC_PASSED"},
        acceptance={"verdict": "passed"},
    )

    assert record["status"] == "allowed"
    assert record["manager"]["verdict"] == "RELEASE_GO"


def test_release_gate_phase_honours_release_manager_no_go():
    router = AgentRouter()
    router.register("release_manager", _release_manager("RELEASE_NO_GO\n需人工确认风险。"))

    record = ProjectOrchestrator(agent_router=router)._run_release_gate_phase(
        integration={"status": "passed"},
        qa={"verdict": "QA_PASSED"},
        security={"verdict": "SEC_PASSED"},
        acceptance={"verdict": "passed"},
    )

    assert record["status"] == "blocked"
    assert record["blocking_code"] == "release_manager_no_go"
    assert record["reason"] == "release manager verdict is RELEASE_NO_GO"


def test_sre_phase_keeps_deterministic_degradation(tmp_path: Path):
    router = AgentRouter()
    router.register("sre", _sre_agent("SRE_READY\n部署指引已就绪。"))

    sre = ProjectOrchestrator(agent_router=router)._run_sre_phase(tmp_path, release=None)

    assert sre["verdict"] == "SRE_DEGRADED"
    assert "deployment_guide" in sre["failed_checks"]
    assert sre["review"]["verdict"] == "SRE_READY"
    assert (tmp_path / "docs" / "sre_readiness.md").is_file()
