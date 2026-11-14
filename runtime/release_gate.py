"""Deterministic release go/no-go gate.

Standard flow: no release is started unless the quality evidence allows it.
The gate consumes only recorded evidence - integration regression status,
QA verdict and the security audit verdict - and returns the blockers. The
release-manager agent can add a ``RELEASE_NO_GO`` on top, but cannot waive a
deterministic blocker.
"""

from __future__ import annotations

from typing import Any


def evaluate_release_gate(
    *,
    integration: dict[str, Any] | None = None,
    qa: dict[str, Any] | None = None,
    security: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``allowed`` / ``blocked`` with the explicit blocker list."""
    blockers: list[dict[str, str]] = []

    if isinstance(integration, dict) and integration.get("status") == "failed":
        blockers.append({"code": "integration_failed", "reason": "产品级集成回归失败"})
    if isinstance(qa, dict) and qa.get("verdict") == "QA_FAILED":
        blockers.append({"code": "qa_failed", "reason": "QA 对抗测试判定为 QA_FAILED"})
    if isinstance(security, dict) and security.get("verdict") == "SEC_FAILED":
        blockers.append({"code": "security_failed", "reason": "安全审计存在高危发现"})

    return {
        "status": "blocked" if blockers else "allowed",
        "blockers": blockers,
    }
