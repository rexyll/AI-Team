"""Deterministic security audit for delivered products.

The security engineer role owns the decision, but its evidence must be
reproducible and offline-verifiable: secrets and dangerous constructs are
detected by pattern rules over the deliverable's text files, dependency
declarations are recorded as advisory evidence, and the verdict is derived
deterministically. The agent layer only interprets this digest; it can
raise the verdict to ``SEC_FAILED`` but cannot lower a deterministic failure.

Severity policy:

* ``high``  - hard credentials (private keys, cloud/provider tokens) and
  high-risk constructs (TLS verification disabled, shell execution with
  ``shell=True``, unsafe YAML loading, pickle deserialisation). A single
  high finding fails the audit and blocks a release.
* ``medium`` - generic credential assignments and ``eval``/``exec`` usage.
  Reported for triage, does not block by itself.

The report never echoes a raw secret: evidence lines are masked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from runtime.dependency_scan import scan_deliverable_dependencies

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "coverage",
    "artifacts",
}

_TEXT_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".kt",
    ".go", ".rb", ".php", ".cs", ".rs", ".swift", ".sql", ".sh", ".bash",
    ".ps1", ".bat", ".cmd", ".yml", ".yaml", ".json", ".toml", ".ini",
    ".cfg", ".conf", ".env", ".properties", ".gradle", ".md", ".txt",
    ".dockerfile",
}

_MAX_FILE_BYTES = 1_000_000

_SECRET_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
        "high",
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "high"),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "high"),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "high"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"), "high"),
    (
        "generic_credential_assignment",
        re.compile(
            r"""(?ix)
            (?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)
            \s*[:=]\s*
            (?:['"][A-Za-z0-9_\-./+]{16,}['"]|(?![$<{]))[A-Za-z0-9_\-./+]{24,}
            """,
        ),
        "medium",
    ),
)

_DANGEROUS_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("shell_execution", re.compile(r"\bshell\s*=\s*True\b"), "high"),
    ("tls_verification_disabled", re.compile(r"\bverify\s*=\s*False\b"), "high"),
    ("pickle_deserialization", re.compile(r"\bpickle\.(?:loads|load)\("), "high"),
    (
        "unsafe_yaml_load",
        re.compile(r"\byaml\.(?:load|unsafe_load)\s*\("),
        "high",
    ),
    ("dynamic_eval", re.compile(r"\beval\s*\("), "medium"),
    ("dynamic_exec", re.compile(r"\bexec\s*\("), "medium"),
)


def _iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name.lower() == "dockerfile":
            pass
        elif path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


_TOKEN_REDACTIONS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
)


def _mask(line: str) -> str:
    """Mask literal credential material so a report never leaks a secret."""
    text = line.strip()[:160]
    for pattern in _TOKEN_REDACTIONS:
        text = pattern.sub("***", text)
    return re.sub(r"(['\"])[^'\"]{6,}\1", r"\1***\1", text)


def run_security_audit(deliverable_root: str | Path) -> dict[str, Any]:
    """Scan one deliverable and derive a deterministic security verdict."""
    root = Path(deliverable_root)
    if not root.is_dir():
        return {
            "status": "skipped",
            "verdict": "SEC_SKIPPED",
            "reason": "deliverable root does not exist",
            "findings": [],
            "files_scanned": 0,
            "high_severity": 0,
        }

    findings: list[dict[str, Any]] = []
    files_scanned = 0
    for path in _iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_scanned += 1
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule, pattern, severity in (*_SECRET_RULES, *_DANGEROUS_RULES):
                if pattern.search(line):
                    findings.append(
                        {
                            "rule": rule,
                            "severity": severity,
                            "path": relative,
                            "line": line_number,
                            "evidence": _mask(line),
                        }
                    )

    findings.sort(key=lambda item: (item["path"], item["line"], item["rule"]))
    high = [item for item in findings if item["severity"] == "high"]
    dependency = scan_deliverable_dependencies(root)
    verdict = "SEC_FAILED" if high else "SEC_PASSED"
    return {
        "status": "completed",
        "verdict": verdict,
        "files_scanned": files_scanned,
        "findings": findings,
        "high_severity": len(high),
        "medium_severity": len(findings) - len(high),
        "dependency_scan": dependency,
    }


def render_security_report(audit: dict[str, Any], *, review: dict[str, Any] | None = None) -> str:
    """Render the human-readable security audit report (``docs/security_audit.md``)."""
    lines = [
        "# 安全审计报告（Security Audit）",
        "",
        f"- 结论：**{audit.get('verdict', 'SEC_SKIPPED')}**",
        f"- 扫描文件数：{audit.get('files_scanned', 0)}",
        f"- 高危发现：{audit.get('high_severity', 0)}",
        f"- 中危发现：{audit.get('medium_severity', 0)}",
        "",
        "## 发现清单",
        "",
    ]
    findings = audit.get("findings") or []
    if findings:
        lines.extend(["| 严重级别 | 规则 | 位置 | 证据（已脱敏） |", "| --- | --- | --- | --- |"])
        for item in findings:
            lines.append(
                f"| {item['severity']} | {item['rule']} | "
                f"`{item['path']}:{item['line']}` | `{item['evidence']}` |"
            )
    else:
        lines.append("未发现可疑模式。")

    dependency = audit.get("dependency_scan") or {}
    lines.extend(["", "## 依赖声明审计（参考，不单独阻断）", ""])
    if dependency.get("status") == "completed":
        lines.append(f"- 声明依赖：{len(dependency.get('declared', []))} 项")
        lines.append(f"- 未锁定版本：{', '.join(dependency.get('unpinned', [])) or '无'}")
        lines.append(
            f"- 未声明的第三方导入：{', '.join(dependency.get('undeclared_imports', [])) or '无'}"
        )
        lookup = dependency.get("vulnerability_lookup") or {}
        lines.append(f"- 漏洞库查询：{lookup.get('status', 'unavailable')}（{lookup.get('reason', '')}）")
    else:
        lines.append(f"- 跳过：{dependency.get('reason', '无可审计的交付物根目录')}")

    if review:
        lines.extend(["", "## 安全工程师复核", ""])
        lines.append(f"- Agent 结论：{review.get('verdict', 'UNKNOWN')}")
        if review.get("summary"):
            lines.append(f"- 说明：{review['summary']}")

    return "\n".join(lines).rstrip() + "\n"


def write_security_report(
    deliverable_root: str | Path,
    audit: dict[str, Any],
    *,
    review: dict[str, Any] | None = None,
) -> Path:
    """Write ``docs/security_audit.md`` and return its path."""
    root = Path(deliverable_root)
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "security_audit.md"
    path.write_text(render_security_report(audit, review=review), encoding="utf-8")
    return path


def security_evidence_digest(audit: dict[str, Any], review: dict[str, Any] | None = None) -> str:
    """Compact JSON digest handed to the security agent for triage."""
    return json.dumps(
        {
            "deterministic_verdict": audit.get("verdict"),
            "files_scanned": audit.get("files_scanned", 0),
            "high_severity": audit.get("high_severity", 0),
            "medium_severity": audit.get("medium_severity", 0),
            "findings": [
                {
                    "rule": item["rule"],
                    "severity": item["severity"],
                    "path": item["path"],
                    "line": item["line"],
                }
                for item in (audit.get("findings") or [])[:40]
            ],
            "agent_verdict": (review or {}).get("verdict"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
