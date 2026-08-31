"""Validated, provider-independent LLM configuration contract.

This module deliberately delegates resolution to :mod:`config.model` so the
existing environment semantics remain the single source of truth.  It adds a
side-effect-free validation/snapshot boundary for callers that need to inspect
configuration before creating an LLM client.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.model import (
    SUPPORTED_ROLES,
    ProviderProfile,
    declared_provider_names,
    get_developer_count,
    get_provider_profile,
    resolve_developer_llm_spec,
    resolve_role_llm_spec,
)


class ConfigurationError(ValueError):
    """Raised when the effective LLM configuration is incomplete or invalid."""


@dataclass(frozen=True)
class RoleConfiguration:
    role: str
    provider: str
    model: str


@dataclass(frozen=True)
class LLMConfiguration:
    """Immutable effective LLM configuration with no live client objects."""

    providers: tuple[ProviderProfile, ...]
    roles: tuple[RoleConfiguration, ...]
    developer_count: int

    def role(self, role: str) -> RoleConfiguration:
        normalized = role.strip().lower()
        for item in self.roles:
            if item.role == normalized:
                return item
        raise KeyError(normalized)

    def provider(self, name: str) -> ProviderProfile:
        normalized = name.strip().lower()
        for item in self.providers:
            if item.name == normalized:
                return item
        raise KeyError(normalized)


def load_configuration() -> LLMConfiguration:
    """Resolve and validate the complete effective LLM configuration.

    Resolution is deterministic and follows the existing contract:
    role-specific provider/model, then provider model, then DEFAULT_MODEL.
    Developer instances additionally honor DEVELOPER_N overrides before the
    shared Developer configuration.
    """

    names = declared_provider_names()
    if not names:
        raise ConfigurationError(
            "No LLM provider is configured. Set DEFAULT_PROVIDER and "
            "<PROVIDER>_API_KEY/<PROVIDER>_BASE_URL in .env."
        )

    try:
        providers = tuple(get_provider_profile(name) for name in names)
        roles = tuple(
            RoleConfiguration(role, *resolve_role_llm_spec(role))
            for role in SUPPORTED_ROLES
        )
        developer_count = get_developer_count()
        # Validate every configured Developer instance without constructing a
        # client or making a network request.
        for index in range(1, developer_count + 1):
            resolve_developer_llm_spec(index)
    except (ValueError, RuntimeError) as exc:
        raise ConfigurationError(str(exc)) from exc

    return LLMConfiguration(
        providers=providers,
        roles=roles,
        developer_count=developer_count,
    )


def configuration_precedence() -> tuple[str, ...]:
    """Return the stable precedence rules for documentation and tooling."""

    return (
        "role-specific provider/model",
        "provider default model",
        "DEFAULT_MODEL",
        "for Developer N: DEVELOPER_N_* then DEVELOPER_* then shared defaults",
    )
