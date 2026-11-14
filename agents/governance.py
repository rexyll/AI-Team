"""Governance agents: security engineer, release/operations and release manager.

These three roles close the standard software-development team:

* ``security`` - reviews the deterministic security-audit digest, returns
  ``SEC_PASSED`` / ``SEC_FAILED``. It cannot waive a deterministic failure.
* ``sre`` - reviews the deterministic deployment-readiness digest, returns
  ``SRE_READY`` / ``SRE_NOT_READY``. External deployment remains out of
  scope; the verdict is about the evidence shipped in the deliverable.
* ``release_manager`` - reviews the release gate digest and returns
  ``RELEASE_GO`` / ``RELEASE_NO_GO``. Deterministic blockers always win.

All three are pure LLM-level roles: they hold no tool surface, write no
files and run no commands, so a governance decision cannot alter product
code. Their rationale is recorded as evidence by the orchestrator.
"""

from __future__ import annotations

import json

from agents.base import BaseAgent
from runtime.agent_result import AgentResult
from runtime.task import Task
from security.prompt_injection import untrusted_content


def _first_verdict(text: str, allowed: tuple[str, ...]) -> str:
    """Return the first verdict token that appears in the response."""
    upper = text.upper()
    hits = [(upper.find(token), token) for token in allowed if token in upper]
    if not hits:
        return "UNKNOWN"
    return min(hits)[1]


def _summary_line(text: str, verdicts: tuple[str, ...] = ()) -> str:
    """Return the first rationale line, skipping a leading verdict token."""
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#-* ").strip()
        if not cleaned:
            continue
        if verdicts and cleaned.upper().strip(".:,;。：") in verdicts:
            continue
        return cleaned[:240]
    return ""


class _ReviewAgent(BaseAgent):
    """Shared LLM-only review behaviour for governance verdicts."""

    VERDICTS: tuple[str, ...] = ()
    DATA_KEY = ""
    SYSTEM_PROMPT = ""

    def _evidence_text(self, task: Task) -> str:
        evidence = task.context.get("evidence")
        if isinstance(evidence, str) and evidence.strip():
            return evidence.strip()
        return json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True, indent=2)

    def _build_prompt(self, task: Task, evidence: str) -> str:
        raise NotImplementedError

    def run(self, task: Task) -> AgentResult:
        evidence = self._evidence_text(task)
        prompt = self._build_prompt(task, evidence)
        response = self._generate(
            prompt,
            system_prompt=self.SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=1500,
        )
        verdict = _first_verdict(str(response), self.VERDICTS)
        record = {"verdict": verdict, "summary": _summary_line(str(response), self.VERDICTS)}
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message=str(response).strip(),
            data={self.DATA_KEY: record},
        )


_SECURITY_PROMPT = """
你是一名资深应用安全工程师（Application Security Engineer）。

职责：
1. 复核确定性安全审计的发现，判断是否存在真正可利用的高危风险
2. 区分真实凭据泄漏/危险构造与误报（示例值、变量引用、测试夹具）
3. 结合依赖声明审计给出发布前必须修复的事项

判定：
- 存在真实高危风险必须输出 SEC_FAILED
- 无高危风险输出 SEC_PASSED
- 确定性审计已判定 SEC_FAILED 时，你不得将其改为 SEC_PASSED

输出要求：第一行只输出 SEC_PASSED 或 SEC_FAILED，随后用不超过 200 字给出理由。
你不修改代码、不写文件、不执行命令、不调用任何工具。
"""

_SRE_PROMPT = """
你是一名资深发布/运维工程师（Release / Site Reliability Engineer）。

职责：
1. 复核部署就绪检查结果：部署指引是否可执行、监控契约/运行手册是否齐备
2. 指出上线前必须补齐的运维证据（安装、启动、回退、监控、告警）
3. 对未覆盖的外部部署环境如实标注，不臆造已完成的事实

判定：
- 关键检查全部通过输出 SRE_READY
- 存在失败检查输出 SRE_NOT_READY
- 不得把确定性失败改为 SRE_READY

输出要求：第一行只输出 SRE_READY 或 SRE_NOT_READY，随后用不超过 200 字给出理由。
你不修改代码、不写文件、不执行命令、不调用任何工具。
"""

_RELEASE_PROMPT = """
你是一名资深发布经理（Release Manager）。

职责：
1. 基于集成回归、QA、安全审计与验收证据判断是否允许发布
2. 明确列出阻断发布的事项与需人工确认的风险
3. 只依据已记录证据做判断，不假设未验证的能力

判定：
- 证据无阻断项输出 RELEASE_GO
- 存在阻断项或关键证据缺失输出 RELEASE_NO_GO
- 确定性门禁已阻断时，你不得输出 RELEASE_GO

输出要求：第一行只输出 RELEASE_GO 或 RELEASE_NO_GO，随后用不超过 200 字给出理由。
你不修改代码、不写文件、不执行命令、不调用任何工具。
"""


class SecurityEngineerAgent(_ReviewAgent):
    """Security engineer: triage deterministic findings into a verdict."""

    VERDICTS = ("SEC_FAILED", "SEC_PASSED")
    DATA_KEY = "security"
    SYSTEM_PROMPT = _SECURITY_PROMPT

    @property
    def role(self) -> str:
        return "security"

    def _build_prompt(self, task: Task, evidence: str) -> str:
        return f"""
请复核下面交付物的安全审计证据，并给出安全结论。

====================
SECURITY EVIDENCE
====================

{untrusted_content("security.evidence", evidence)}

====================
TASK
====================

任务：{untrusted_content("task.title", task.title)}

说明：{untrusted_content("task.description", task.description)}
"""


class SREAgent(_ReviewAgent):
    """Release/operations engineer: deployment readiness review."""

    VERDICTS = ("SRE_NOT_READY", "SRE_READY")
    DATA_KEY = "sre"
    SYSTEM_PROMPT = _SRE_PROMPT

    @property
    def role(self) -> str:
        return "sre"

    def _build_prompt(self, task: Task, evidence: str) -> str:
        return f"""
请复核下面交付物的部署就绪证据，并给出运维结论。

====================
DEPLOYMENT READINESS EVIDENCE
====================

{untrusted_content("sre.evidence", evidence)}

====================
TASK
====================

任务：{untrusted_content("task.title", task.title)}

说明：{untrusted_content("task.description", task.description)}
"""


class ReleaseManagerAgent(_ReviewAgent):
    """Release manager: release go/no-go decision over recorded evidence."""

    VERDICTS = ("RELEASE_NO_GO", "RELEASE_GO")
    DATA_KEY = "release"
    SYSTEM_PROMPT = _RELEASE_PROMPT

    @property
    def role(self) -> str:
        return "release_manager"

    def _build_prompt(self, task: Task, evidence: str) -> str:
        return f"""
请复核下面的发布门禁证据，并给出发布结论。

====================
RELEASE GATE EVIDENCE
====================

{untrusted_content("release.evidence", evidence)}

====================
TASK
====================

任务：{untrusted_content("task.title", task.title)}

说明：{untrusted_content("task.description", task.description)}
"""


def parse_governance_verdict(role: str, text: str) -> str:
    """Parse a verdict from free-form model output for the given role."""
    if not isinstance(role, str) or not role:
        raise ValueError("role must be a non-empty string")
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if role == "security":
        return _first_verdict(text, ("SEC_FAILED", "SEC_PASSED"))
    if role == "sre":
        return _first_verdict(text, ("SRE_NOT_READY", "SRE_READY"))
    if role == "release_manager":
        return _first_verdict(text, ("RELEASE_NO_GO", "RELEASE_GO"))
    raise ValueError(f"unknown governance role: {role}")
