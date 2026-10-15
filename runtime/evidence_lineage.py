from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from runtime.provenance import EvidenceProvenance, provenance_from_value


def collect_lineage(value: Any, parents: Iterable[Any] = ()) -> list[EvidenceProvenance]:
    """Return an explicit child-to-root provenance chain.

    Parent links are resolved only against supplied payloads. An evidence id
    is never guessed to exist merely because it appears in parent_evidence_id.
    """
    payloads = (value, *tuple(parents))
    index: dict[str, EvidenceProvenance] = {}
    for payload in payloads:
        provenance = provenance_from_value(payload)
        if provenance is not None:
            index[provenance.evidence_id] = provenance

    current = provenance_from_value(value)
    chain: list[EvidenceProvenance] = []
    seen: set[str] = set()
    while current is not None:
        if current.evidence_id in seen:
            raise ValueError(f"evidence provenance cycle detected at {current.evidence_id}")
        seen.add(current.evidence_id)
        chain.append(current)
        if current.parent_evidence_id is None:
            break
        current = index.get(current.parent_evidence_id)
        if current is None:
            break
    return chain
