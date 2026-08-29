from __future__ import annotations

from typing import Any, Iterable

from security.runtime_capability import DEFAULT_RUNTIME_CAPABILITY_POLICY, RuntimeCapabilityPolicy
from tools.registry import TOOL_REGISTRY, ToolRegistry


def filter_tool_schemas(
    role: str,
    schemas: Iterable[dict[str, Any]],
    *,
    capability_policy: RuntimeCapabilityPolicy | None = None,
) -> list[dict[str, Any]]:
    """Return only schemas whose tools the role is authorized to use.

    Exposure is intentionally deny-by-default. Unknown or malformed schemas are
    omitted rather than exposed to the model; execution authorization remains a
    separate mandatory boundary in ToolInvocationService.
    """
    policy = capability_policy or DEFAULT_RUNTIME_CAPABILITY_POLICY
    names: list[str] = []
    by_name: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        names.append(name)
        by_name[name] = schema
    allowed = policy.filter_tool_names(role, names)
    return [by_name[name] for name in allowed]


def tool_schemas_for_role(
    role: str,
    *,
    registry: ToolRegistry | None = None,
    capability_policy: RuntimeCapabilityPolicy | None = None,
) -> list[dict[str, Any]]:
    """Build the LLM-visible tool schema set for an agent role."""
    active_registry = registry or TOOL_REGISTRY
    return filter_tool_schemas(
        role,
        active_registry.schemas(),
        capability_policy=capability_policy,
    )
