"""Deterministic delivery packaging.

The final step of the delivery phase: bundle the deliverable directory
(product code + standard documents + manifest) into a single zip archive a
customer can take as-is. Packaging reuses the delivery-manifest exclusion
rules, writes members in sorted order for reproducible archives, and verifies
its own output by re-reading the archive and comparing per-member checksums
against the delivery manifest entries.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

from runtime.delivery_manifest import collect_deliverables


def create_delivery_package(
    deliverable_root: str | Path,
    *,
    output_dir: str | Path | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Zip every deliverable under ``deliverable_root`` and verify the result.

    Returns a detached package record: archive path, member count, size and
    the archive SHA-256. Members are the same files the delivery manifest
    lists, so the archive is exactly what the customer is told they receive.
    """
    root = Path(deliverable_root)
    if not root.is_dir():
        raise ValueError(f"deliverable root does not exist: {root}")
    entries = collect_deliverables(root)
    if not entries:
        raise ValueError(f"no deliverable files found under: {root}")

    output_dir = Path(output_dir) if output_dir is not None else root.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    package_name = f"{root.name}-delivery.zip" if root.name else "delivery.zip"
    archive_path = output_dir / package_name

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for entry in entries:  # collect_deliverables returns sorted paths
            bundle.write(root / str(entry["path"]), arcname=str(entry["path"]))

    verification = verify_package(archive_path, entries)
    if not verification["ok"]:
        archive_path.unlink(missing_ok=True)
        raise ValueError(f"delivery package failed verification: {verification['problems']}")

    data = archive_path.read_bytes()
    return {
        "archive": str(archive_path),
        "files": len(entries),
        "size": len(data),
        "checksum": hashlib.sha256(data).hexdigest(),
    }


def verify_package(
    archive_path: str | Path,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Re-read a package archive and compare each member against the entries.

    Every manifest entry must be present with a matching size and SHA-256,
    and the archive must contain no unexpected members.
    """
    archive_path = Path(archive_path)
    problems: list[str] = []
    expected = {str(entry["path"]): entry for entry in entries}
    try:
        with zipfile.ZipFile(archive_path, "r") as bundle:
            members = {name: bundle.read(name) for name in bundle.namelist()}
    except (zipfile.BadZipFile, OSError) as exc:
        return {"ok": False, "problems": [f"unreadable archive: {exc}"]}

    for name, data in members.items():
        if name not in expected:
            problems.append(f"unexpected member: {name}")
            continue
        entry = expected[name]
        if len(data) != entry["size"]:
            problems.append(f"size mismatch: {name}")
        if hashlib.sha256(data).hexdigest() != entry["checksum"]:
            problems.append(f"checksum mismatch: {name}")
    for name in expected:
        if name not in members:
            problems.append(f"missing member: {name}")
    return {"ok": not problems, "problems": problems}
