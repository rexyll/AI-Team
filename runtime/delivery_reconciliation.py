from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from runtime.delivery_store import DeliveryDecision, DurableDeliveryStore


class SinkMutationState(StrEnum):
    """Authoritative observation of the external mutation."""

    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SinkReconciliation:
    """Authoritative sink observation for one delivery identity."""

    delivery_key: str
    state: SinkMutationState


class AuthoritativeSink(Protocol):
    """Business sink capable of answering whether a delivery mutation happened."""

    def reconcile(self, delivery_key: str) -> SinkReconciliation:
        """Return an authoritative observation; never infer from worker liveness."""
        ...


class ReconciliationRequired(RuntimeError):
    """Raised when an ambiguous sink state cannot safely be resolved."""


class AuthoritativeDeliveryReconciler:
    """Translate authoritative sink observations into delivery-store actions.

    The mapping is intentionally strict:

    * APPLIED -> commit the existing processing marker without replaying it.
    * NOT_APPLIED -> release the marker so the delivery can be retried.
    * UNKNOWN -> leave the marker processing and require a later reconciliation.

    No callback is replayed by this coordinator. The authoritative sink is the
    only component allowed to establish whether the external mutation happened.
    """

    def __init__(self, store: DurableDeliveryStore, sink: AuthoritativeSink) -> None:
        self.store = store
        self.sink = sink

    def reconcile(self, key: str) -> DeliveryDecision:
        observation = self.sink.reconcile(key)
        if not isinstance(observation, SinkReconciliation):
            raise TypeError("sink.reconcile() must return SinkReconciliation")
        if observation.delivery_key != key:
            raise ValueError("sink reconciliation delivery key mismatch")

        if observation.state == SinkMutationState.APPLIED:
            return self.store.recover_processing(key, "commit")
        if observation.state == SinkMutationState.NOT_APPLIED:
            return self.store.recover_processing(key, "retry")
        if observation.state == SinkMutationState.UNKNOWN:
            raise ReconciliationRequired(
                f"Delivery {key} remains ambiguous; authoritative sink state is unknown"
            )
        raise ValueError(f"Unsupported sink mutation state: {observation.state!r}")
