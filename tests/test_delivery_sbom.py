from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from runtime.delivery_sbom import (
    build_delivery_evidence,
    verify_delivery_provenance,
    write_build_evidence,
    write_delivery_provenance,
    write_delivery_sbom,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _lock_text(name: str = "Foo_Bar", version: str = "1.2.3") -> str:
    digest = "a" * 64
    return f"{name}=={version} \\\n    --hash=sha256:{digest}\n"


def test_cyclonedx_sbom_uses_lock_components_purls_and_hashes(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "foo-bar==1.2.3\n")
    lock = tmp_path / "requirements-linux-py314.lock"
    _write(lock, _lock_text())
    evidence_sha = hashlib.sha256(b"{}").hexdigest()

    result = write_delivery_sbom(
        tmp_path,
        project="sample-app",
        build_evidence_sha256=evidence_sha,
        lock_file=lock.name,
    )

    bom = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["completeness"] == "complete"
    assert result["lock_sha256"] == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.6"
    assert bom["metadata"]["component"]["name"] == "sample-app"
    component = bom["components"][0]
    assert component["name"] == "Foo_Bar"
    assert component["version"] == "1.2.3"
    assert component["purl"] == "pkg:pypi/foo-bar@1.2.3"
    assert component["hashes"] == [{"alg": "SHA-256", "content": "a" * 64}]
    assert {"name": "ai-team:license-status", "value": "unknown"} in component["properties"]
    assert {
        "name": "ai-team:sbom:build-evidence-sha256",
        "value": evidence_sha,
    } in bom["metadata"]["properties"]


def test_missing_lock_generates_declared_only_partial_sbom(tmp_path: Path):
    _write(
        tmp_path / "requirements.txt",
        "requests>=2.0\n"
        "pinned-lib==1.4.2\n",
    )
    evidence_sha = hashlib.sha256(b"{}").hexdigest()

    result = write_delivery_sbom(
        tmp_path,
        project="sample-app",
        build_evidence_sha256=evidence_sha,
    )

    bom = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert result["status"] == "partial"
    assert result["completeness"] == "partial"
    assert result["dependency_scope"] == "declared-only"
    assert result["lock_sha256"] is None
    by_name = {component["name"]: component for component in bom["components"]}
    assert "version" not in by_name["requests"]
    assert by_name["pinned-lib"]["version"] == "1.4.2"
    assert all("hashes" not in component for component in bom["components"])


def test_malformed_lock_fails_closed_instead_of_falling_back(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "requests==2.0.0\n")
    _write(
        tmp_path / "requirements-linux-py314.lock",
        "requests==2.0.0 \\\n    # missing required hash\n",
    )

    with pytest.raises(ValueError, match="no SHA-256 hashes"):
        write_delivery_sbom(
            tmp_path,
            project="sample-app",
            build_evidence_sha256=hashlib.sha256(b"{}").hexdigest(),
            lock_file="requirements-linux-py314.lock",
        )


def test_build_evidence_is_minimized_and_deterministic(tmp_path: Path):
    evidence = build_delivery_evidence(
        project="sample-app",
        integration={
            "status": "passed",
            "rounds": 1,
            "output_tail": "must not be copied",
            "prompt": "must not be copied",
            "summary": {"passed": 12, "failed": 0, "skipped": 2},
        },
        qa={"verdict": "passed", "raw_report": "private"},
        security={"verdict": "passed", "secret": "private"},
    )

    assert evidence["integration"]["status"] == "passed"
    assert evidence["integration"]["summary"] == {
        "passed": 12,
        "failed": 0,
        "skipped": 2,
    }
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert "must not be copied" not in serialized
    assert "private" not in serialized

    first = write_build_evidence(tmp_path, evidence)
    first_bytes = Path(first["path"]).read_bytes()
    second = write_build_evidence(tmp_path, evidence)
    assert Path(second["path"]).read_bytes() == first_bytes
    assert first["sha256"] == second["sha256"]


def test_sbom_is_deterministic_for_identical_inputs(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "sample==1.0.0\n")
    evidence_sha = hashlib.sha256(b"{}").hexdigest()

    first = write_delivery_sbom(
        tmp_path,
        project="sample-app",
        build_evidence_sha256=evidence_sha,
    )
    first_bytes = Path(first["path"]).read_bytes()
    second = write_delivery_sbom(
        tmp_path,
        project="sample-app",
        build_evidence_sha256=evidence_sha,
    )

    assert Path(second["path"]).read_bytes() == first_bytes
    assert first["sha256"] == second["sha256"]


def test_provenance_binds_archive_and_detects_tampering(tmp_path: Path):
    _write(tmp_path / "app.py", "print('ok')\n")
    lock = tmp_path / "requirements-linux-py314.lock"
    _write(lock, _lock_text())
    evidence = write_build_evidence(
        tmp_path,
        build_delivery_evidence(project="sample-app", integration={"status": "passed"}),
    )
    sbom = write_delivery_sbom(
        tmp_path,
        project="sample-app",
        build_evidence_sha256=evidence["sha256"],
        lock_file=lock.name,
    )
    manifest = tmp_path / "DELIVERY_MANIFEST.md"
    _write(manifest, "# manifest\n")
    archive = tmp_path / "sample-app.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in ("app.py", lock.name, "DELIVERY_BUILD_EVIDENCE.json", "DELIVERY_SBOM.cdx.json", manifest.name):
            bundle.write(tmp_path / name, arcname=name)

    provenance = write_delivery_provenance(
        archive,
        sbom_path=sbom["path"],
        manifest_path=manifest,
        build_evidence_path=evidence["path"],
        lock_path=lock,
    )
    assert provenance["status"] == "verified"
    assert provenance["signature_status"] == "unsigned"
    assert verify_delivery_provenance(provenance["path"], archive_path=archive)["ok"] is True

    archive.write_bytes(archive.read_bytes() + b"tampered")
    verification = verify_delivery_provenance(provenance["path"], archive_path=archive)
    assert verification["ok"] is False
    assert "delivery archive SHA-256 mismatch" in verification["problems"]


def test_repository_python314_lock_is_fully_parsed(tmp_path: Path):
    repository_root = Path(__file__).resolve().parents[1]
    source_lock = repository_root / "requirements-linux-py314.lock"
    lock = tmp_path / source_lock.name
    shutil.copyfile(source_lock, lock)
    _write(tmp_path / "requirements.txt", "openai==3.1.0\n")
    result = write_delivery_sbom(
        tmp_path,
        project="ai-team",
        build_evidence_sha256=hashlib.sha256(b"{}").hexdigest(),
        lock_file=lock.name,
    )
    bom = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["components"] == 17
    assert all(component.get("hashes") for component in bom["components"])


def test_declared_sbom_rejects_unexpanded_requirement_includes(tmp_path: Path):
    _write(
        tmp_path / "requirements.txt",
        "-r base-requirements.txt\n"
        "requests==2.0.0\n",
    )
    with pytest.raises(ValueError, match="unsupported requirement directive"):
        write_delivery_sbom(
            tmp_path,
            project="sample-app",
            build_evidence_sha256=hashlib.sha256(b"{}").hexdigest(),
        )


def test_sbom_preserves_platform_markers_from_lock(tmp_path: Path):
    marker = 'sys_platform == "win32"'
    lock = tmp_path / "requirements-windows-py314.lock"
    _write(
        lock,
        "colorama==0.4.6; " + marker + " \\\n"
        "    --hash=sha256:" + ("b" * 64) + "\n",
    )
    result = write_delivery_sbom(
        tmp_path,
        project="sample-app",
        build_evidence_sha256=hashlib.sha256(b"{}").hexdigest(),
        lock_file=lock.name,
    )
    bom = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert {
        "name": "ai-team:environment-marker",
        "value": marker,
    } in bom["components"][0]["properties"]
