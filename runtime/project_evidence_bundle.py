"""Privacy-minimized evidence bundle for deterministic project E2E runs.

The bundle is written outside the deliverable archive (for example as a CI
artifact). It contains hashes and observed gate facts, not raw requirements,
prompts, command arguments, command output, secrets, or local absolute paths.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from runtime.acceptance import parse_requirement_entries
from runtime.delivery_manifest import collect_deliverables


EVIDENCE_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_TASK_STATES = {"completed", "failed", "blocked", "cancelled"}


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError("evidence values must be finite JSON data") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value))


def _file_sha256(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration_seconds(started_at: Any, completed_at: Any) -> float | None:
    if not isinstance(started_at, str) or not isinstance(completed_at, str):
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None or end.tzinfo is None or end < start:
        return None
    return round((end - start).total_seconds(), 6)


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _tool_record_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    arguments = record.get("arguments", {})
    supplied_digest = record.get("arguments_sha256")
    if supplied_digest is not None:
        if not isinstance(supplied_digest, str) or not _SHA256.fullmatch(supplied_digest):
            raise ValueError("tool evidence arguments_sha256 is invalid")
        arguments_digest = supplied_digest
    else:
        arguments_digest = _sha256_value(arguments)
    summary = {
        "execution_id": record.get("execution_id"),
        "task_id": record.get("task_id"),
        "role": record.get("agent_role"),
        "tool": record.get("tool_name"),
        "status": record.get("status", "unknown"),
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        # Arguments may contain paths or user input. Store only a stable digest.
        "arguments_sha256": arguments_digest,
        "duration_seconds": _duration_seconds(
            record.get("started_at"), record.get("completed_at")
        ),
    }
    for field in ("execution_id", "task_id", "role", "tool"):
        if not isinstance(summary[field], str) or not summary[field].strip():
            raise ValueError(f"tool evidence is missing {field}")
    if not isinstance(summary["status"], str) or not summary["status"].strip():
        raise ValueError("tool evidence status must be non-empty")
    for field in ("started_at", "completed_at"):
        if summary[field] is not None and not isinstance(summary[field], str):
            raise ValueError(f"tool evidence {field} must be a string or None")
    return summary


def _workspace_summary(context: Mapping[str, Any], task_id: str) -> dict[str, Any] | None:
    lease = context.get("workspace_lease")
    if not isinstance(lease, Mapping):
        return None
    lease_id = lease.get("lease_id")
    disposition = lease.get("disposition")
    if not isinstance(lease_id, str) or not lease_id.strip():
        raise ValueError(f"task {task_id} has a workspace lease without an id")
    if disposition not in {"issued", "merged", "discarded"}:
        raise ValueError(f"task {task_id} has an invalid workspace lease disposition")
    merge = context.get("workspace_merge")
    merge_summary = None
    if isinstance(merge, Mapping):
        merge_summary = {
            "changed": list(merge.get("changed") or [])[:500],
            "added": list(merge.get("added") or [])[:500],
            "deleted": list(merge.get("deleted") or [])[:500],
        }
    environment = context.get("workspace_environment")
    environment_summary = None
    if isinstance(environment, Mapping):
        environment_summary = {
            "status": environment.get("status"),
            "adapter": environment.get("adapter"),
            "created": bool(environment.get("created", False)),
        }
    return {
        "lease_id": lease_id,
        "task_id": str(lease.get("task_id") or task_id),
        "disposition": disposition,
        "merge": merge_summary,
        "environment": environment_summary,
    }


def _task_summaries(project: Any) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    manager = getattr(project, "last_task_manager", None)
    if manager is None or not callable(getattr(manager, "get_all_tasks", None)):
        raise ValueError("project has no completed task manager")
    tasks = manager.get_all_tasks()
    summaries: list[dict[str, Any]] = []
    tool_records: dict[str, dict[str, Any]] = {}
    developer_count = 0
    lease_count = 0
    merged_count = 0
    discarded_count = 0
    incomplete_count = 0
    for task in tasks:
        task_id = _get(task, "id")
        role = _get(task, "role")
        status = str(_get(task, "status", "unknown"))
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task evidence requires a non-empty task id")
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"task {task_id} has no role")
        dependencies = _get(task, "dependencies", [])
        if not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
            raise ValueError(f"task {task_id} dependencies must be a list of strings")
        title = _get(task, "title", "")
        description = _get(task, "description", "")
        context = _get(task, "context", {})
        if not isinstance(context, Mapping):
            context = {}
        workspace = _workspace_summary(context, task_id) if role == "developer" else None
        if role == "developer":
            developer_count += 1
            if workspace is None:
                incomplete_count += 1
            else:
                lease_count += 1
                if workspace["disposition"] == "merged":
                    merged_count += 1
                elif workspace["disposition"] == "discarded":
                    discarded_count += 1
                else:
                    incomplete_count += 1
        def decision_summary(value: Any) -> dict[str, Any] | None:
            if not isinstance(value, Mapping):
                return None
            return {
                key: value.get(key)
                for key in ("status", "verdict", "approved", "passed")
                if key in value
                and (
                    isinstance(value.get(key), (str, int, float, bool))
                    or value.get(key) is None
                )
            }

        summaries.append({
            "id": task_id,
            "role": role,
            "status": status,
            "terminal": status in _TERMINAL_TASK_STATES,
            "dependencies": list(dependencies),
            "title_sha256": _sha256_value(str(title)),
            "description_sha256": _sha256_value(str(description)),
            "tester": decision_summary(_get(task, "test_result")),
            "reviewer": decision_summary(_get(task, "review_result")),
            "workspace": workspace,
        })
        history = context.get("tool_execution_history")
        if isinstance(history, list):
            for record in history:
                if not isinstance(record, Mapping):
                    raise ValueError(f"task {task_id} has malformed tool evidence")
                summary = _tool_record_summary(record)
                existing = tool_records.get(summary["execution_id"])
                if existing is not None and existing != summary:
                    raise ValueError("conflicting tool evidence for one execution id")
                tool_records[summary["execution_id"]] = summary
    isolation_status = (
        "not_applicable"
        if developer_count == 0
        else "passed"
        if incomplete_count == 0 and lease_count == developer_count
        else "incomplete"
    )
    workspace_evidence = {
        "status": isolation_status,
        "developer_tasks": developer_count,
        "leases_observed": lease_count,
        "leases_merged": merged_count,
        "leases_discarded": discarded_count,
        "leases_incomplete": incomplete_count,
    }
    return summaries, workspace_evidence, list(tool_records.values())


def _integration_summary(integration: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(integration, Mapping):
        return None, []
    suite = integration.get("suite")
    suite_summary = None
    if isinstance(suite, Mapping):
        suite_summary = {
            "status": suite.get("status", "unknown"),
            "exit_code": suite.get("exit_code"),
            "summary": dict(suite.get("summary") or {}),
            "duration_seconds": suite.get("duration_seconds"),
            "test_case_count": len(suite.get("test_cases") or []),
            "test_cases": [
                {
                    "selector": item.get("selector"),
                    "status": item.get("status"),
                    "duration_seconds": item.get("duration_seconds"),
                }
                for item in (suite.get("test_cases") or [])[:500]
                if isinstance(item, Mapping)
            ],
        }
    static = integration.get("static")
    static_summary = None
    if isinstance(static, Mapping):
        static_summary = {
            "status": static.get("status", "unknown"),
            "tools": {
                str(name): {
                    "status": record.get("status", "unknown"),
                    "enforced": record.get("enforced"),
                }
                for name, record in (static.get("tools") or {}).items()
                if isinstance(record, Mapping)
            },
        }
    adapter = integration.get("adapter")
    adapter_summary = None
    adapter_tools: list[dict[str, Any]] = []
    if isinstance(adapter, Mapping):
        actions = adapter.get("actions") or {}
        adapter_summary = {
            "status": adapter.get("status", "unknown"),
            "adapter": adapter.get("adapter"),
            "language": adapter.get("language"),
            "signals": list(adapter.get("signals") or []),
            "actions": {
                str(name): {
                    "status": result.get("status", "unknown"),
                    "exit_code": result.get("exit_code"),
                }
                for name, result in actions.items()
                if isinstance(result, Mapping)
            },
        }
        history = adapter.get("tool_execution_history")
        if isinstance(history, list):
            adapter_tools = [
                _tool_record_summary(item)
                for item in history
                if isinstance(item, Mapping)
            ]
    return {
        "status": integration.get("status", "unknown"),
        "rounds": integration.get("rounds", 0),
        "suite": suite_summary,
        "static": static_summary,
        "adapter": adapter_summary,
    }, adapter_tools


def _acceptance_summary(value: Any) -> dict[str, Any] | None:
    summary = _gate_summary(value)
    if summary is None:
        return None
    summary["traceability_verdict"] = value.get("traceability_verdict", "unknown")
    summary["executable_verdict"] = value.get("executable_verdict", "unknown")
    requirement_results = []
    for requirement in (value.get("requirements") or [])[:500]:
        if not isinstance(requirement, Mapping):
            continue
        requirement_results.append({
            "requirement_id": requirement.get("req_id"),
            "tests": [
                {
                    "test_id": test.get("test_id"),
                    "status": test.get("status", "unknown"),
                    "selector": test.get("selector"),
                }
                for test in (requirement.get("tests") or [])[:100]
                if isinstance(test, Mapping)
            ],
        })
    summary["requirements"] = requirement_results
    return summary


def _gate_summary(value: Any, *, verdict_key: str = "verdict") -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    summary = {
        "status": value.get("status", "unknown"),
        "verdict": value.get(verdict_key, "unknown"),
    }
    for field in ("blocking_code", "failed_checks", "test_count", "total_requirements"):
        if field in value:
            item = value[field]
            if isinstance(item, (str, int, float, bool)) or item is None:
                summary[field] = item
            elif isinstance(item, list):
                summary[field] = item[:100]
    for field in ("gaps", "warnings", "blockers"):
        if isinstance(value.get(field), list):
            summary[f"{field}_count"] = len(value[field])
    executed_tool_calls = value.get("executed_tool_calls")
    if isinstance(executed_tool_calls, int) and not isinstance(executed_tool_calls, bool):
        summary["executed_tool_calls"] = executed_tool_calls
    history = value.get("tool_execution_history")
    if isinstance(history, list):
        summary["tool_invocation_count"] = len(history)
        summary["tool_invocation_statuses"] = [
            {
                "tool": item.get("tool_name"),
                "status": item.get("status"),
            }
            for item in history[:100]
            if isinstance(item, Mapping)
        ]
    return summary


def _artifact_summary(delivery: Mapping[str, Any], deliverable_root: Path) -> dict[str, Any]:
    manifest_value = delivery.get("manifest")
    manifest = Path(str(manifest_value)) if isinstance(manifest_value, str) and manifest_value else None
    manifest_hash = None
    if manifest is not None:
        resolved_root = deliverable_root.resolve()
        resolved_manifest = manifest.resolve()
        try:
            manifest_relative = resolved_manifest.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ValueError("delivery manifest must be inside the deliverable root") from exc
        manifest_hash = _file_sha256(resolved_manifest)
    else:
        manifest_relative = None
    members = [
        item for item in collect_deliverables(deliverable_root)
        if item.get("path") != manifest_relative
    ]
    package_value = delivery.get("package")
    package_summary: dict[str, Any] | None = None
    if isinstance(package_value, Mapping):
        archive_value = package_value.get("archive")
        archive = Path(str(archive_value)) if isinstance(archive_value, str) and archive_value else None
        computed = _file_sha256(archive) if archive is not None else None
        expected = package_value.get("checksum")
        package_summary = {
            "status": "available" if computed is not None else "unavailable",
            "filename": archive.name if archive is not None else None,
            "sha256": computed,
            "recorded_sha256_matches": (
                computed == expected if isinstance(expected, str) and computed is not None else None
            ),
        }
    else:
        package_summary = {"status": "not_created"}
    sidecars: dict[str, Any] = {}
    for key in ("build_evidence", "sbom", "provenance"):
        record = delivery.get(key)
        if isinstance(record, Mapping):
            raw_path = record.get("path")
            path = Path(str(raw_path)) if isinstance(raw_path, str) and raw_path else None
            sidecars[key] = {
                "status": record.get("status", "unknown"),
                "filename": path.name if path is not None else None,
                "sha256": _file_sha256(path) if path is not None else None,
            }
    return {
        "manifest": {
            "status": "available" if manifest_hash else "unavailable",
            "path": manifest_relative,
            "sha256": manifest_hash,
            "member_count": len(members),
            "members": members[:2000],
        },
        "package": package_summary,
        "sidecars": sidecars,
        "smoke": _gate_summary(delivery.get("smoke"), verdict_key="status"),
    }


def build_project_evidence_bundle(
    project: Any,
    *,
    requirement: str,
    deliverable_root: str | Path,
    evidence_level: str,
    role_execution: Mapping[str, str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, privacy-minimized snapshot of one project run."""
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("requirement must be a non-empty string")
    if evidence_level not in {
        "deterministic_orchestration",
        "live_provider_llm",
        "external_deployment",
    }:
        raise ValueError("unsupported evidence_level")
    root = Path(deliverable_root)
    if not root.is_dir():
        raise ValueError("deliverable root does not exist")
    delivery = getattr(project, "last_delivery", None)
    if not isinstance(delivery, Mapping):
        raise ValueError("project has no delivery evidence")
    plan = getattr(project, "last_plan", None)
    if not isinstance(plan, Mapping):
        plan = {}
    analysis = getattr(project, "last_requirement_analysis", None)
    analysis = analysis if isinstance(analysis, str) else ""
    project_id = getattr(project, "_project_id", None) or plan.get("project_id")
    project_name = plan.get("project") or root.name
    requirements = [
        {
            "id": item.req_id,
            "priority": item.priority,
            "has_acceptance_criteria": item.has_acceptance_criteria,
        }
        for item in parse_requirement_entries(analysis)
    ]
    tasks, workspace, task_tools = _task_summaries(project)
    integration, adapter_tools = _integration_summary(delivery.get("integration"))
    tools_by_id: dict[str, dict[str, Any]] = {}
    qa_evidence = delivery.get("qa")
    qa_history = qa_evidence.get("tool_execution_history") if isinstance(qa_evidence, Mapping) else None
    qa_tools = [
        _tool_record_summary(item)
        for item in qa_history
        if isinstance(item, Mapping)
    ] if isinstance(qa_history, list) else []
    for record in task_tools + adapter_tools + qa_tools:
        execution_id = record["execution_id"]
        existing = tools_by_id.get(execution_id)
        if existing is not None and existing != record:
            raise ValueError("conflicting tool evidence for one execution id")
        tools_by_id[execution_id] = record
    profile = getattr(project, "last_project_profile", None)
    profile_data = profile.to_dict() if callable(getattr(profile, "to_dict", None)) else None
    result = getattr(project, "last_result", None)
    scm = getattr(project, "last_scm_observation", None)
    scm_summary = None
    if isinstance(scm, Mapping):
        scm_summary = {
            key: scm.get(key)
            for key in (
                "status", "pull_request_state", "ci_status", "review_status",
                "head_sha", "pull_request_number",
            )
            if scm.get(key) is not None
        }
    bundle: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_level": evidence_level,
        "project": {
            "id": project_id if isinstance(project_id, str) else None,
            "name": str(project_name),
            "status": str(getattr(result, "status", "unknown")),
            "success": getattr(result, "success", None),
        },
        "requirement": {
            "sha256": _sha256_bytes(requirement.encode("utf-8")),
            "character_count": len(requirement),
            "ids": requirements,
        },
        "project_profile": profile_data,
        "task_graph": {
            "planned_task_count": len(plan.get("tasks") or []),
            "tasks": tasks,
            "workspace_isolation": workspace,
        },
        "tool_invocations": sorted(
            tools_by_id.values(),
            key=lambda item: (str(item.get("started_at") or ""), item["execution_id"]),
        ),
        "gates": {
            "analyst": {
                "status": "available" if analysis.strip() else "not_registered",
                "analysis_sha256": _sha256_bytes(analysis.encode("utf-8")) if analysis.strip() else None,
                "requirement_count": len(requirements),
            },
            "integration": integration,
            "qa": _gate_summary(delivery.get("qa")),
            "security": _gate_summary(delivery.get("security")),
            "acceptance": _acceptance_summary(delivery.get("acceptance")),
            "release_gate": _gate_summary(delivery.get("release_gate"), verdict_key="status"),
            "sre": _gate_summary(delivery.get("sre")),
            "monitoring": _gate_summary(delivery.get("monitoring"), verdict_key="status"),
            "dependency_scan": _gate_summary(delivery.get("dependency_scan"), verdict_key="status"),
            "scm_observation": scm_summary,
        },
        "artifacts": _artifact_summary(delivery, root),
        "release": (
            {
                key: delivery["release"].get(key)
                for key in ("status", "version", "tag", "commit")
                if delivery["release"].get(key) is not None
            }
            if isinstance(delivery.get("release"), Mapping)
            else {"status": "not_requested"}
        ),
        "role_execution": dict(role_execution or {}),
        "limitations": list(limitations or []),
        "privacy": {
            "raw_requirement_included": False,
            "raw_prompt_or_analysis_included": False,
            "raw_command_arguments_or_output_included": False,
            "secret_values_included": False,
            "local_absolute_paths_included": False,
        },
    }
    bundle["evidence_sha256"] = _sha256_value(bundle)
    validate_project_evidence_bundle(bundle)
    return bundle


def validate_project_evidence_bundle(bundle: Mapping[str, Any]) -> None:
    """Validate the schema version and the canonical content digest."""
    if not isinstance(bundle, Mapping):
        raise TypeError("evidence bundle must be a mapping")
    if bundle.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported project evidence schema version")
    digest = bundle.get("evidence_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    unsigned = dict(bundle)
    unsigned.pop("evidence_sha256")
    if _sha256_value(unsigned) != digest:
        raise ValueError("project evidence digest mismatch")
    privacy = bundle.get("privacy")
    if not isinstance(privacy, Mapping) or any(
        privacy.get(field) is not False
        for field in (
            "raw_requirement_included",
            "raw_prompt_or_analysis_included",
            "raw_command_arguments_or_output_included",
            "secret_values_included",
            "local_absolute_paths_included",
        )
    ):
        raise ValueError("project evidence privacy declaration is invalid")


def write_project_evidence_bundle(
    project: Any,
    *,
    requirement: str,
    deliverable_root: str | Path,
    output_path: str | Path,
    evidence_level: str,
    role_execution: Mapping[str, str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Atomically write one evidence bundle and return its external reference."""
    bundle = build_project_evidence_bundle(
        project,
        requirement=requirement,
        deliverable_root=deliverable_root,
        evidence_level=evidence_level,
        role_execution=role_execution,
        limitations=limitations,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(_canonical_json(bundle) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return {
        "path": str(destination),
        "filename": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": bundle["evidence_sha256"],
        "schema_version": EVIDENCE_SCHEMA_VERSION,
    }
