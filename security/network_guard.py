"""Enforcement boundary for agent-controlled network operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from security.network import NetworkPolicy


T = TypeVar("T")


class NetworkEgressDenied(PermissionError):
    """Raised when a network operation is outside the configured policy."""


def execute_network_operation(
    policy: NetworkPolicy,
    url: str,
    operation: Callable[[str], T],
) -> T:
    """Validate a destination before executing an agent-controlled operation.

    The callback receives the validated, original URL only after the policy
    accepts it. Policy failures happen before the callback can run.
    """
    if not isinstance(policy, NetworkPolicy):
        raise TypeError("policy must be a NetworkPolicy")
    if not callable(operation):
        raise TypeError("operation must be callable")

    try:
        validated_url = policy.validate_url(url)
    except (PermissionError, ValueError) as exc:
        raise NetworkEgressDenied(str(exc)) from exc

    return operation(validated_url)
