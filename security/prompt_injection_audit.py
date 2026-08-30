from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class PromptInjectionFinding:
    """Safe, persistence-ready description of one injection signal.

    The finding intentionally contains no copy of the inspected content. This
    makes it suitable for execution/audit events without turning the security
    trail into a secret or hostile-payload sink.
    """

    rule_id: str
    source: str
    match_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise ValueError("rule_id must be a non-empty string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        if not isinstance(self.match_count, int) or self.match_count <= 0:
            raise ValueError("match_count must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "source": self.source,
            "match_count": self.match_count,
        }


# Only high-confidence instruction-override signals belong here. Ordinary
# words such as "security", "password", or "command" are intentionally not
# enough to create an audit event on their own.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_previous_instructions",
        re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|rules?|messages?)\b", re.I),
    ),
    (
        "override_system_policy",
        re.compile(r"\b(?:ignore|override|bypass|disable)\s+(?:the\s+)?(?:system|security|safety)\s+(?:prompt|policy|rules?|controls?)\b", re.I),
    ),
    (
        "request_hidden_instructions",
        re.compile(r"\b(?:reveal|show|print|expose|leak)\s+(?:the\s+)?(?:system\s+prompt|hidden\s+instructions?|developer\s+message)\b", re.I),
    ),
    (
        "request_secret_disclosure",
        re.compile(r"\b(?:reveal|show|print|expose|leak)\s+(?:the\s+)?(?:api\s+key|access\s+token|secret|credential|password)\b", re.I),
    ),
    (
        "tool_authorization_bypass",
        re.compile(r"\b(?:bypass|skip|disable)\s+(?:the\s+)?(?:tool|workspace|permission|authorization|approval)\s+(?:guard|check|policy|restriction|validation)\b", re.I),
    ),
)


def _iter_text(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _iter_text(item)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_text(item)


def detect_prompt_injection(value: Any, *, source: str) -> list[PromptInjectionFinding]:
    """Detect high-confidence injection signals without retaining input text.

    This is deliberately a signal detector, not an authorization decision.
    Runtime capability and workspace policies remain authoritative.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")

    counts: dict[str, int] = {}
    for text in _iter_text(value):
        for rule_id, pattern in _RULES:
            matches = pattern.findall(text)
            if matches:
                counts[rule_id] = counts.get(rule_id, 0) + len(matches)

    return [
        PromptInjectionFinding(rule_id=rule_id, source=source, match_count=counts[rule_id])
        for rule_id in sorted(counts)
    ]


def build_audit_payload(findings: Iterable[PromptInjectionFinding], *, stage: str) -> dict[str, Any]:
    """Build a JSON-safe audit payload containing metadata only.

    The payload contains rule/source/count metadata and never includes the
    inspected value, matched text, prompt, tool output, or secret material.
    """
    if not isinstance(stage, str) or not stage.strip():
        raise ValueError("stage must be a non-empty string")
    normalized = list(findings)
    if any(not isinstance(item, PromptInjectionFinding) for item in normalized):
        raise TypeError("findings must contain PromptInjectionFinding values")
    return {
        "stage": stage.strip(),
        "finding_count": len(normalized),
        "findings": [item.to_dict() for item in normalized],
        "contains_raw_content": False,
    }
