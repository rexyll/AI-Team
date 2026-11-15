"""CycloneDX SBOM and delivery provenance generation.

The SBOM is included in the delivery archive. The archive digest is bound
after packaging in an unsigned sidecar to avoid a self-referential checksum.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

_LOCK_PACKAGE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\\\s;]+)(?:\s*;\s*(?P<marker>.+?))?\s*\\?$"
)
_LOCK_HASH = re.compile(r"^\s*--hash=sha256:(?P<digest>[0-9a-fA-F]{64})\s*\\?$")
_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<specifier>.*)$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return _sha256_bytes(data)


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pypi_purl(name: str, version: str | None) -> str:
    normalized = quote(_normalize_name(name), safe="-._~")
    value = f"pkg:pypi/{normalized}"
    if version:
        value += "@" + quote(version, safe=".-_~")
    return value


def _parse_lock(path: Path) -> list[dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        package_match = _LOCK_PACKAGE.match(line)
        if package_match is not None:
            name = package_match.group("name")
            normalized = _normalize_name(name)
            if normalized in packages:
                raise ValueError(f"duplicate package in lock at line {line_number}: {name}")
            current = {
                "name": name,
                "version": package_match.group("version"),
                "marker": package_match.group("marker"),
                "hashes": set(),
            }
            packages[normalized] = current
            continue

        hash_match = _LOCK_HASH.match(line)
        if hash_match is not None:
            if current is None:
                raise ValueError(f"orphan hash in lock at line {line_number}")
            current["hashes"].add(hash_match.group("digest").lower())
            continue

        raise ValueError(f"unsupported lock syntax at line {line_number}")

    if not packages:
        raise ValueError("lock file contains no pinned packages")

    components: list[dict[str, Any]] = []
    for item in packages.values():
        hashes = sorted(item["hashes"])
        if not hashes:
            raise ValueError(f"lock package has no SHA-256 hashes: {item['name']}")
        components.append({
            "name": item["name"],
            "version": item["version"],
            "hashes": hashes,
            "purl": _pypi_purl(item["name"], item["version"]),
            "resolution": "locked",
            "marker": item["marker"],
        })
    return sorted(components, key=lambda item: item["purl"])


def _parse_declared_requirements(path: Path) -> list[dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-") or "://" in line or " @ " in line or line.startswith("git+"):
            raise ValueError(f"unsupported requirement directive at line {line_number}")
        requirement_parts = line.split(";", 1)
        requirement = requirement_parts[0].strip()
        marker = requirement_parts[1].strip() if len(requirement_parts) == 2 else None
        match = _REQUIREMENT.match(requirement)
        if match is None:
            raise ValueError(f"unsupported requirement syntax at line {line_number}")
        name = match.group("name")
        specifier = match.group("specifier").strip()
        version = None
        if specifier.startswith("==") and not specifier.startswith("==="):
            candidate = specifier[2:].strip()
            if candidate and not any(token in candidate for token in "<>=!~,* "):
                version = candidate
        normalized = _normalize_name(name)
        if normalized in components:
            raise ValueError(f"duplicate requirement at line {line_number}: {name}")
        components[normalized] = {
            "name": name,
            "version": version,
            "hashes": [],
            "purl": _pypi_purl(name, version),
            "resolution": "declared-pinned" if version else "declared-unresolved",
            "declared_requirement": requirement,
            "marker": marker,
        }
    return sorted(components.values(), key=lambda item: item["purl"])


def _select_lock_file(root: Path, explicit: str | Path | None) -> Path | None:
    if explicit is not None:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
        if resolved_root not in resolved_candidate.parents:
            raise ValueError("lock file must be inside the deliverable root")
        if not resolved_candidate.is_file():
            raise ValueError("explicit lock file does not exist")
        return resolved_candidate

    system = "windows" if os.name == "nt" else "linux" if sys.platform.startswith("linux") else platform.system().lower()
    python_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    platform_candidates = sorted(root.glob(f"requirements-{system}-{python_tag}.lock"))
    if len(platform_candidates) > 1:
        raise ValueError("multiple platform lock files match the active environment")
    if platform_candidates:
        return platform_candidates[0]
    generic = root / "requirements.lock"
    if generic.is_file():
        return generic
    return None


def _safe_evidence_summary(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = (
        "status",
        "verdict",
        "rounds",
        "test_count",
        "total_requirements",
        "traceability_verdict",
        "executable_verdict",
        "blocking_code",
    )
    result: dict[str, Any] = {}
    for key in allowed:
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) or item is None:
            if item is not None:
                result[key] = item
    if isinstance(value.get("vulnerability_lookup"), Mapping):
        lookup_status = value["vulnerability_lookup"].get("status")
        if isinstance(lookup_status, str):
            result["vulnerability_lookup_status"] = lookup_status
    for source_key, target_key in (
        ("undeclared_imports", "undeclared_import_count"),
        ("unpinned", "unpinned_dependency_count"),
    ):
        items = value.get(source_key)
        if isinstance(items, list):
            result[target_key] = len(items)
    summary = value.get("summary")
    if isinstance(summary, Mapping):
        counts = {
            key: summary[key]
            for key in ("passed", "failed", "errors", "skipped", "xfailed", "xpassed")
            if isinstance(summary.get(key), int)
        }
        if counts:
            result["summary"] = counts
    return result


def build_delivery_evidence(
    *,
    project: str | None,
    integration: Mapping[str, Any] | None = None,
    qa: Mapping[str, Any] | None = None,
    security: Mapping[str, Any] | None = None,
    acceptance: Mapping[str, Any] | None = None,
    dependency_scan: Mapping[str, Any] | None = None,
    release: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a privacy-minimized, deterministic summary of delivery gates."""
    return {
        "schema_version": 1,
        "project": project or "unknown",
        "integration": _safe_evidence_summary(integration),
        "qa": _safe_evidence_summary(qa),
        "security": _safe_evidence_summary(security),
        "acceptance": _safe_evidence_summary(acceptance),
        "dependency_scan": _safe_evidence_summary(dependency_scan),
        "release": _safe_evidence_summary(release),
    }


def write_build_evidence(
    deliverable_root: str | Path,
    evidence: Mapping[str, Any],
    *,
    filename: str = "DELIVERY_BUILD_EVIDENCE.json",
) -> dict[str, Any]:
    root = Path(deliverable_root)
    if not root.is_dir():
        raise ValueError("deliverable root does not exist")
    path = root / filename
    digest = _write_json(path, dict(evidence))
    return {"status": "completed", "path": str(path), "sha256": digest}


def write_delivery_sbom(
    deliverable_root: str | Path,
    *,
    project: str | None,
    build_evidence_sha256: str,
    lock_file: str | Path | None = None,
    requirements_file: str = "requirements.txt",
    filename: str = "DELIVERY_SBOM.cdx.json",
) -> dict[str, Any]:
    """Write a CycloneDX 1.6 SBOM; missing locks are explicitly partial."""
    root = Path(deliverable_root)
    if not root.is_dir():
        raise ValueError("deliverable root does not exist")
    if not _SHA256.fullmatch(build_evidence_sha256):
        raise ValueError("build evidence digest must be a lowercase SHA-256 hex digest")

    requirements_path = root / requirements_file
    if requirements_path.is_file():
        requirements_sha256 = _sha256_file(requirements_path)
    else:
        requirements_sha256 = None

    selected_lock = _select_lock_file(root, lock_file)
    if selected_lock is not None:
        components = _parse_lock(selected_lock)
        dependency_scope = "locked-transitive"
        completeness = "complete"
        lock_sha256 = _sha256_file(selected_lock)
        lock_member = selected_lock.relative_to(root.resolve()).as_posix()
    elif requirements_path.is_file():
        components = _parse_declared_requirements(requirements_path)
        dependency_scope = "declared-only"
        completeness = "partial"
        lock_sha256 = None
        lock_member = None
    else:
        components = []
        dependency_scope = "none"
        completeness = "partial"
        lock_sha256 = None
        lock_member = None

    bom_components = []
    for item in components:
        properties = [
            {"name": "ai-team:resolution", "value": item["resolution"]},
            {"name": "ai-team:license-status", "value": "unknown"},
        ]
        if item.get("marker"):
            properties.append({
                "name": "ai-team:environment-marker",
                "value": item["marker"],
            })
        if item.get("declared_requirement"):
            properties.append({
                "name": "ai-team:declared-requirement",
                "value": item["declared_requirement"],
            })
        if item.get("marker"):
            properties.append({
                "name": "ai-team:environment-marker",
                "value": item["marker"],
            })
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": item["purl"],
            "name": item["name"],
            "purl": item["purl"],
            "scope": "required",
            "properties": properties,
        }
        if item["version"]:
            component["version"] = item["version"]
        if item["hashes"]:
            component["hashes"] = [
                {"alg": "SHA-256", "content": digest}
                for digest in item["hashes"]
            ]
        bom_components.append(component)

    metadata_properties = [
        {"name": "ai-team:sbom:completeness", "value": completeness},
        {"name": "ai-team:sbom:dependency-scope", "value": dependency_scope},
        {"name": "ai-team:sbom:build-evidence-sha256", "value": build_evidence_sha256},
    ]
    if requirements_sha256:
        metadata_properties.append({
            "name": "ai-team:sbom:requirements-sha256",
            "value": requirements_sha256,
        })
    if lock_sha256:
        metadata_properties.append({
            "name": "ai-team:sbom:lock-sha256",
            "value": lock_sha256,
        })

    identity = {
        "project": project or root.name,
        "components": bom_components,
        "properties": metadata_properties,
    }
    serial = uuid.uuid5(uuid.NAMESPACE_URL, _sha256_bytes(_canonical_json(identity)))
    bom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": project or root.name or "deliverable",
            },
            "tools": {
                "components": [{
                    "type": "application",
                    "name": "AI-Team Delivery SBOM Generator",
                    "version": "1.0.0",
                }]
            },
            "properties": metadata_properties,
        },
        "components": bom_components,
    }
    path = root / filename
    digest = _write_json(path, bom)
    return {
        "status": "completed" if completeness == "complete" else "partial",
        "format": "CycloneDX",
        "spec_version": "1.6",
        "path": str(path),
        "sha256": digest,
        "components": len(bom_components),
        "completeness": completeness,
        "dependency_scope": dependency_scope,
        "requirements_sha256": requirements_sha256,
        "lock_path": str(selected_lock) if selected_lock is not None else None,
        "lock_member": lock_member,
        "lock_sha256": lock_sha256,
        "build_evidence_sha256": build_evidence_sha256,
    }


def verify_delivery_provenance(
    provenance_path: str | Path,
    *,
    archive_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify archive and all bound members against an unsigned sidecar."""
    sidecar = Path(provenance_path)
    problems: list[str] = []
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "problems": ["provenance sidecar is unreadable"]}

    archive = Path(archive_path) if archive_path is not None else sidecar.parent / record.get("artifact", {}).get("file", "")
    if not archive.is_file():
        return {"ok": False, "problems": ["delivery archive is missing"]}
    if _sha256_file(archive) != record.get("artifact", {}).get("sha256"):
        problems.append("delivery archive SHA-256 mismatch")

    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            member_bytes: dict[str, bytes] = {}
            for field in ("sbom", "manifest", "build_evidence", "lock"):
                expected = record.get(field, {})
                member = expected.get("member")
                digest = expected.get("sha256")
                if not member or not digest:
                    continue
                try:
                    data = bundle.read(member)
                except KeyError:
                    problems.append(f"archive member missing: {member}")
                    continue
                member_bytes[field] = data
                if _sha256_bytes(data) != digest:
                    problems.append(f"archive member SHA-256 mismatch: {member}")

            if "sbom" in member_bytes and "build_evidence" in record:
                try:
                    bom = json.loads(member_bytes["sbom"])
                    properties = {
                        item.get("name"): item.get("value")
                        for item in bom.get("metadata", {}).get("properties", [])
                    }
                    expected_evidence = record["build_evidence"].get("sha256")
                    if properties.get("ai-team:sbom:build-evidence-sha256") != expected_evidence:
                        problems.append("SBOM build-evidence digest binding mismatch")
                    expected_lock = record.get("lock", {}).get("sha256")
                    sbom_lock = properties.get("ai-team:sbom:lock-sha256")
                    if expected_lock and sbom_lock != expected_lock:
                        problems.append("SBOM lock digest binding mismatch")
                    if not expected_lock and properties.get("ai-team:sbom:completeness") != "partial":
                        problems.append("SBOM without a lock is not marked partial")
                except (json.JSONDecodeError, AttributeError, TypeError):
                    problems.append("CycloneDX SBOM is unreadable or malformed")
    except (OSError, zipfile.BadZipFile):
        problems.append("delivery archive is unreadable")

    return {"ok": not problems, "problems": problems}


def write_delivery_provenance(
    archive_path: str | Path,
    *,
    sbom_path: str | Path,
    manifest_path: str | Path,
    build_evidence_path: str | Path,
    lock_path: str | Path | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Bind a finished ZIP to its SBOM/evidence/manifest without a hash cycle."""
    archive = Path(archive_path)
    if not archive.is_file():
        raise ValueError("delivery archive does not exist")
    sbom = Path(sbom_path)
    manifest = Path(manifest_path)
    evidence = Path(build_evidence_path)
    for required in (sbom, manifest, evidence):
        if not required.is_file():
            raise ValueError(f"required delivery evidence is missing: {required.name}")

    record: dict[str, Any] = {
        "schema_version": 1,
        "signature": {"status": "unsigned"},
        "artifact": {"file": archive.name, "sha256": _sha256_file(archive)},
        "sbom": {"member": sbom.name, "sha256": _sha256_file(sbom)},
        "manifest": {"member": manifest.name, "sha256": _sha256_file(manifest)},
        "build_evidence": {
            "member": evidence.name,
            "sha256": _sha256_file(evidence),
        },
    }
    if lock_path is not None and Path(lock_path).is_file():
        lock = Path(lock_path)
        record["lock"] = {
            "member": lock.relative_to(sbom.parent).as_posix(),
            "sha256": _sha256_file(lock),
        }
    else:
        record["lock"] = {"member": None, "sha256": None, "status": "missing"}

    sidecar = Path(filename) if filename else Path(str(archive) + ".provenance.json")
    digest = _write_json(sidecar, record)
    verification = verify_delivery_provenance(sidecar, archive_path=archive)
    if not verification["ok"]:
        sidecar.unlink(missing_ok=True)
        raise ValueError(f"delivery provenance verification failed: {verification['problems']}")
    return {
        "status": "verified" if record["lock"]["sha256"] else "partial",
        "path": str(sidecar),
        "sha256": digest,
        "archive_sha256": record["artifact"]["sha256"],
        "sbom_sha256": record["sbom"]["sha256"],
        "build_evidence_sha256": record["build_evidence"]["sha256"],
        "verification": verification,
        "signature_status": "unsigned",
    }
