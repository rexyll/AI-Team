from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from runtime.provenance import EvidenceProvenance, provenance_from_value


def collect_lineage(value: Any) -> list[EvidenceProvenance]:
    """Return the provenance chain from an evidence payload to its root.

    The returned order is child -> parent. Only explicit provenance links are
    followed; an arbitrary evidence id is never treated as a parent by guess.
    """
    current = provenance_from_value(value)
    chain: list[EvidenceProvenance] = []
    seen: set[str] = set()
    while current is not None:
        if current.evidence_id in seen:
            raise ValueError(f"evidence provenance cycle detected at {current.evidence_id}")
        seen.add(current.evidence_id)
        chain.append(current)
        parent_id = current.parent_evidence_id
        if parent_id is None:
            break
        current = _find_parent_from_payloads(parent_id, ())
    return chain


def collect_lineage_from_values(values: Iterable[Any], *, root: Any | None = None) -> list[EvidenceProvenance]:
    """Build a child-to-root lineage from a set of supplied evidence payloads."""
    payloads = tuple(values)
    if root is not None:
        payloads = payloads + (root,)
    index: dict[str, EvidenceProvenance] = {}
    for value in payloads:
        provenance = provenance_from_value(value)
        if provenance is not None:
            index[provenance.evidence_id] = provenance

    start = next((provenance_from_value(value) for value in payloads if provenance_from_value(value) is not None), None)
    if start is None:
        return []

    chain: list[EvidenceProvenance] = []
    seen: set[str] = set()
    current = start
    while current is not None:
        if current.evidence_id in seen:
            raise ValueError(f"evidence provenance cycle detected at {current.evidence_id}")
        seen.add(current.evidence_id)
        chain.append(current)
        current = index.get(current.parent_evidence_id) if current.parent_evidence_id else None
    return chain


def _find_parent_from_payloads(parent_id: str, payloads: Iterable[Any]) -> EvidenceProvenance | None:
    for value in payloads:
        provenance = provenance_from_value(value)
        if provenance is not None and provenance.evidence_id == parent_id:
            return provenance
    return None
