"""Team completeness: governance roles are registered and stay tool-free."""

from __future__ import annotations

import pytest

from agents.governance import (
    ReleaseManagerAgent,
    SREAgent,
    SecurityEngineerAgent,
    parse_governance_verdict,
)
from config.model import SUPPORTED_ROLES
from runtime.agent_config import AgentConfig
from runtime.agent_factory import create_agent_router
from runtime.llm.base import BaseLLM
from runtime.task import Task
from security.runtime_capability import ROLE_CAPABILITIES


class _StaticLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("governance agents must not use tools")


def _governance_task(role: str, evidence: str = "{}") -> Task:
    task = Task(
        id=f"{role.upper()}-001",
        title=f"{role} review",
        description="review the recorded evidence",
        role=role,
        status="ready",
    )
    task.context["evidence"] = evidence
    return task


@pytest.mark.parametrize("role", ["security", "sre", "release_manager"])
def test_governance_roles_are_supported_and_tool_free(role):
    assert role in SUPPORTED_ROLES
    assert ROLE_CAPABILITIES[role] == frozenset()


def test_factory_registers_governance_roles():
    router = create_agent_router()

    assert isinstance(router.get_agent("security"), SecurityEngineerAgent)
    assert isinstance(router.get_agent("sre"), SREAgent)
    assert isinstance(router.get_agent("release_manager"), ReleaseManagerAgent)
    assert router.get_agent("security").role == "security"
    assert router.get_agent("sre").role == "sre"
    assert router.get_agent("release_manager").role == "release_manager"


def test_security_agent_returns_verdict_and_fences_evidence():
    llm = _StaticLLM("SEC_PASSED\n未发现真实凭据泄漏。")
    agent = SecurityEngineerAgent(AgentConfig(role="security", model="security-model"), llm=llm)

    result = agent.run(_governance_task("security", evidence='{"high_severity": 0}'))

    assert result.data["security"]["verdict"] == "SEC_PASSED"
    assert result.data["security"]["summary"].startswith("未发现真实凭据泄漏")
    assert 'source="security.evidence"' in llm.prompts[0]


def test_sre_agent_returns_not_ready_verdict():
    llm = _StaticLLM("SRE_NOT_READY\n回退方式未记录。")
    agent = SREAgent(AgentConfig(role="sre", model="sre-model"), llm=llm)

    result = agent.run(_governance_task("sre", evidence='{"failed_checks": ["deployment_guide"]}'))

    assert result.data["sre"]["verdict"] == "SRE_NOT_READY"


def test_release_manager_agent_returns_no_go():
    llm = _StaticLLM("RELEASE_NO_GO\n安全审计未通过。")
    agent = ReleaseManagerAgent(
        AgentConfig(role="release_manager", model="release-model"), llm=llm
    )

    result = agent.run(_governance_task("release_manager", evidence='{"security": "SEC_FAILED"}'))

    assert result.data["release"]["verdict"] == "RELEASE_NO_GO"


@pytest.mark.parametrize(
    ("role", "text", "expected"),
    [
        ("security", "结论：SEC_FAILED\n原因", "SEC_FAILED"),
        ("security", "结论：SEC_PASSED", "SEC_PASSED"),
        ("sre", "结论：SRE_READY", "SRE_READY"),
        ("sre", "结论：SRE_NOT_READY", "SRE_NOT_READY"),
        ("release_manager", "结论：RELEASE_GO", "RELEASE_GO"),
        ("release_manager", "结论：RELEASE_NO_GO", "RELEASE_NO_GO"),
        ("security", "没有给出结论", "UNKNOWN"),
    ],
)
def test_parse_governance_verdict(role, text, expected):
    assert parse_governance_verdict(role, text) == expected


def test_parse_governance_verdict_rejects_unknown_role():
    with pytest.raises(ValueError):
        parse_governance_verdict("developer", "PASSED")
