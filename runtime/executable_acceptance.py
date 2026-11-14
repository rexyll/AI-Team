"""Executable requirement-acceptance evidence.

A document reference is not proof that a test ran. This module binds mandatory
requirements to explicit test selectors and evaluates only test cases emitted
by the product integration runner's JUnit report.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.acceptance import RequirementEntry


SPEC_FILENAME = "acceptance_tests.json"
SPEC_SCHEMA_VERSION = 1
DEFAULT_EVIDENCE_MAX_AGE_SECONDS = 24 * 60 * 60


def load_acceptance_test_specs(docs_root: str | Path) -> list[dict[str, str]]:
    """Load and validate the project-authored acceptance test mapping."""
    path = Path(docs_root) / SPEC_FILENAME
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid acceptance test specification: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise ValueError("acceptance test specification schema_version must be 1")
    tests = payload.get("tests")
    if not isinstance(tests, list):
        raise ValueError("acceptance test specification tests must be a list")
    validated: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(tests):
        if not isinstance(item, dict):
            raise ValueError(f"acceptance test entry {index} must be an object")
        test_id = item.get("test_id")
        requirement_id = item.get("requirement_id")
        selector = item.get("selector")
        for field_name, value in (
            ("test_id", test_id),
            ("requirement_id", requirement_id),
            ("selector", selector),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"acceptance test entry {index} {field_name} must be non-empty")
        if not test_id.startswith("AT-"):
            raise ValueError(f"acceptance test id must start with AT-: {test_id}")
        if test_id in seen_ids:
            raise ValueError(f"duplicate acceptance test id: {test_id}")
        if not requirement_id.startswith("REQ-"):
            raise ValueError(f"invalid requirement id: {requirement_id}")
        if selector.startswith(("/", "\\\\")) or ".." in selector.split("::")[0].replace("\\\\", "/").split("/"):
            raise ValueError(f"unsafe acceptance test selector: {selector}")
        seen_ids.add(test_id)
        validated.append({
            "test_id": test_id,
            "requirement_id": requirement_id,
            "selector": selector,
        })
    return validated


def evaluate_executable_acceptance(
    entries: list[RequirementEntry],
    specs: list[dict[str, str]],
    integration: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_EVIDENCE_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Evaluate mandatory REQ coverage against actual JUnit test execution."""
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be a non-negative integer")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    integration = integration if isinstance(integration, dict) else {}
    test_cases = integration.get("test_cases")
    if not isinstance(test_cases, list):
        test_cases = []
    by_selector = {
        item.get("selector"): item
        for item in test_cases
        if isinstance(item, dict) and isinstance(item.get("selector"), str)
    }
    gaps: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    specs_by_req: dict[str, list[dict[str, str]]] = {}
    for spec in specs:
        specs_by_req.setdefault(spec["requirement_id"], []).append(spec)

    integration_status = integration.get("status")
    started_at = integration.get("started_at")
    evidence_age_seconds: float | None = None
    if isinstance(started_at, str):
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if started.tzinfo is not None:
                evidence_age_seconds = max(0.0, (now - started).total_seconds())
        except ValueError:
            evidence_age_seconds = None
    evidence_stale = evidence_age_seconds is None or evidence_age_seconds > max_age_seconds

    known_requirements = {entry.req_id for entry in entries}
    orphan_specs = [spec for spec in specs if spec.get("requirement_id") not in known_requirements]
    for spec in orphan_specs:
        gaps.append(
            f"{spec.get('test_id', 'unknown')} references unknown requirement "
            f"{spec.get('requirement_id', '')}"
        )

    mandatory_unexecuted = False
    mandatory_failed = False
    for entry in entries:
        linked = specs_by_req.get(entry.req_id, [])
        if not linked:
            message = f"{entry.req_id} has no executable acceptance test"
            if entry.priority == "必须":
                gaps.append(message)
            else:
                warnings.append(message)
            records.append({"requirement_id": entry.req_id, "status": "unlinked", "tests": []})
            continue
        test_records: list[dict[str, Any]] = []
        for spec in linked:
            executed = by_selector.get(spec["selector"])
            if executed is None:
                status = "not_executed"
                reason = "selector absent from integration test execution"
            else:
                status = str(executed.get("status") or "unknown")
                reason = None
            test_records.append({
                **spec,
                "status": status,
                "reason": reason,
                "duration_seconds": executed.get("duration_seconds") if executed else None,
                "summary": executed.get("summary") if executed else None,
            })
        if entry.priority == "必须":
            if integration_status != "passed":
                gaps.append(f"{entry.req_id} integration suite status is {integration_status or 'missing'}")
            if evidence_stale:
                gaps.append(f"{entry.req_id} executable evidence is missing or stale")
            for test in test_records:
                if test["status"] != "passed":
                    gaps.append(f"{test['test_id']} {test['status']}: {test.get('reason') or 'test did not pass'}")
                    if test["status"] in {"not_executed", "skipped", "unknown"}:
                        mandatory_unexecuted = True
                    else:
                        mandatory_failed = True
        elif any(test["status"] != "passed" for test in test_records):
            warnings.append(f"{entry.req_id} optional acceptance tests are not all passed")
        records.append({
            "requirement_id": entry.req_id,
            "status": "passed" if test_records and all(t["status"] == "passed" for t in test_records) else "failed",
            "tests": test_records,
        })

    if not entries:
        verdict = "not_applicable"
    elif evidence_stale:
        verdict = "stale"
    elif integration_status in (None, "skipped"):
        verdict = "not_executed"
    elif integration_status != "passed" or mandatory_failed or orphan_specs:
        verdict = "failed"
    elif mandatory_unexecuted:
        verdict = "not_executed"
    else:
        verdict = "failed" if gaps else "passed"
    return {
        "verdict": verdict,
        "gaps": gaps,
        "warnings": warnings,
        "requirements": records,
        "test_count": sum(len(item["tests"]) for item in records),
        "evidence_started_at": started_at,
        "evidence_age_seconds": round(evidence_age_seconds, 3) if evidence_age_seconds is not None else None,
        "evidence_max_age_seconds": max_age_seconds,
    }


def render_executable_acceptance_report(result: dict[str, Any], *, project: str | None = None) -> str:
    lines = ["# 可执行验收证据报告（Executable Acceptance Evidence）", ""]
    if project:
        lines.extend([f"项目：{project}", ""])
    lines.extend([
        f"验收结论：**{str(result.get('verdict', 'unknown')).upper()}**",
        "",
        f"验收测试数：{result.get('test_count', 0)}",
        "",
        "| 需求 | 状态 | 测试 ID | Selector | 执行状态 |",
        "| --- | --- | --- | --- | --- |",
    ])
    for requirement in result.get("requirements", []):
        tests = requirement.get("tests") or []
        if not tests:
            lines.append(f"| {requirement['requirement_id']} | {requirement['status']} | — | — | — |")
        for test in tests:
            lines.append(
                f"| {requirement['requirement_id']} | {requirement['status']} | "
                f"{test['test_id']} | `{test['selector']}` | {test['status']} |"
            )
    for heading, key in (("验收缺口", "gaps"), ("警告", "warnings")):
        values = result.get(key) or []
        if values:
            lines.extend(["", f"## {heading}", ""])
            lines.extend(f"- {value}" for value in values)
    lines.extend([
        "",
        f"证据开始时间：{result.get('evidence_started_at') or '不可用'}",
        f"证据最大有效期：{result.get('evidence_max_age_seconds')} 秒",
        "",
    ])
    return "\n".join(lines)


def write_executable_acceptance_report(
    docs_root: str | Path, result: dict[str, Any], *, project: str | None = None
) -> Path:
    docs = Path(docs_root)
    docs.mkdir(parents=True, exist_ok=True)
    target = docs / "executable_acceptance_report.md"
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(render_executable_acceptance_report(result, project=project), encoding="utf-8")
    temporary.replace(target)
    return target
