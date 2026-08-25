"""Environment-driven configuration for OpenAI-compatible LLM providers.

All provider endpoints, credentials, and model identifiers are supplied by
environment variables (normally loaded from ``.env``). Nothing in this
module contains a provider URL or model identifier as a runtime default.

Configuration layers:

* provider profile: ``<PROVIDER>_API_KEY``, ``<PROVIDER>_BASE_URL``,
  ``<PROVIDER>_MODEL``
* role binding: ``<ROLE>_PROVIDER`` and ``<ROLE>_MODEL``
* global binding: ``DEFAULT_PROVIDER`` and ``DEFAULT_MODEL``
* developer pool: ``DEVELOPER_COUNT`` plus ``DEVELOPER_<N>_PROVIDER`` /
  ``DEVELOPER_<N>_MODEL`` with role/global fallbacks
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

SUPPORTED_ROLES: tuple[str, ...] = (
    "planner",
    "architect",
    "developer",
    "tester",
    "reviewer",
)


@dataclass(frozen=True)
class ProviderProfile:
    """Connection facts for one OpenAI-compatible endpoint."""

    name: str
    api_key_env: str
    base_url: str
    default_model: str

    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


def declared_provider_names() -> list[str]:
    """Return configured provider names in deterministic order."""
    names: list[str] = []
    seen: set[str] = set()

    raw = os.getenv("LLM_PROVIDERS", "")
    for item in raw.split(","):
        name = item.strip().lower()
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    pattern = re.compile(r"^([A-Z0-9_]+)_API_KEY$")
    for var in os.environ:
        match = pattern.match(var)
        if match:
            name = match.group(1).lower()
            if name not in seen:
                seen.add(name)
                names.append(name)

    return names


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is not configured")
    return value


def get_provider_profile(name: str | None = None) -> ProviderProfile:
    """Resolve a provider profile entirely from environment configuration."""
    provider_name = str(name if name is not None else _first_declared_provider()).strip().lower()
    if not provider_name:
        raise ValueError("provider name cannot be empty")

    prefix = provider_name.upper()
    base_url = _required_env(f"{prefix}_BASE_URL")
    default_model = os.getenv(f"{prefix}_MODEL", "").strip()

    return ProviderProfile(
        name=provider_name,
        api_key_env=f"{prefix}_API_KEY",
        base_url=base_url,
        default_model=default_model,
    )


def _first_declared_provider() -> str:
    names = declared_provider_names()
    if not names:
        configured = os.getenv("DEFAULT_PROVIDER", "").strip()
        if configured:
            return configured.lower()
        raise ValueError(
            "No LLM provider is configured. Set DEFAULT_PROVIDER and "
            "<PROVIDER>_API_KEY/<PROVIDER>_BASE_URL in .env."
        )
    return names[0]


_CLIENTS: dict[str, Any] = {}


def get_client_for(profile_name: str | None = None):
    """Return one lazily-created client per configured provider profile."""
    profile = get_provider_profile(profile_name)
    cached = _CLIENTS.get(profile.name)
    if cached is None:
        api_key = profile.api_key()
        if not api_key:
            raise RuntimeError(f"{profile.api_key_env} is not configured")
        cached = OpenAI(api_key=api_key, base_url=profile.base_url)
        _CLIENTS[profile.name] = cached
    return cached


def _resolve_provider_for_role(role: str) -> str:
    prefix = role.upper()
    provider = os.getenv(f"{prefix}_PROVIDER", "").strip()
    if provider:
        return provider.lower()
    provider = os.getenv("DEFAULT_PROVIDER", "").strip()
    if provider:
        return provider.lower()
    return _first_declared_provider()


def resolve_role_llm_spec(role: str) -> tuple[str, str]:
    """Resolve ``(provider, model)`` for a team role."""
    role = role.strip().lower()
    if role not in SUPPORTED_ROLES:
        raise ValueError(f"Unknown role: {role!r}. Supported: {SUPPORTED_ROLES}")

    provider_name = _resolve_provider_for_role(role)
    profile = get_provider_profile(provider_name)

    model = os.getenv(f"{role.upper()}_MODEL", "").strip()
    if not model:
        model = profile.default_model
    if not model:
        model = os.getenv("DEFAULT_MODEL", "").strip()
    if not model:
        raise ValueError(
            f"No model configured for role '{role}'. Set {role.upper()}_MODEL, "
            f"{provider_name.upper()}_MODEL, or DEFAULT_MODEL in .env."
        )
    return profile.name, model


def _parse_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def get_developer_count() -> int:
    """Return the configured Developer pool size."""
    return _parse_positive_int("DEVELOPER_COUNT", 1)


def resolve_developer_llm_spec(index: int) -> tuple[str, str]:
    """Resolve one Developer's ``(provider, model)``.

    Indexes are 1-based and can override the generic developer role:
    ``DEVELOPER_1_PROVIDER`` / ``DEVELOPER_1_MODEL``.
    Missing per-instance values inherit ``DEVELOPER_PROVIDER`` /
    ``DEVELOPER_MODEL`` and then the global/provider defaults.
    """
    if not isinstance(index, int) or isinstance(index, bool) or index < 1:
        raise ValueError("developer index must be a positive integer")

    specific_prefix = f"DEVELOPER_{index}"
    provider = os.getenv(f"{specific_prefix}_PROVIDER", "").strip()
    if not provider:
        provider = os.getenv("DEVELOPER_PROVIDER", "").strip()
    if not provider:
        provider = _resolve_provider_for_role("developer")
    provider = provider.lower()

    profile = get_provider_profile(provider)
    model = os.getenv(f"{specific_prefix}_MODEL", "").strip()
    if not model:
        model = os.getenv("DEVELOPER_MODEL", "").strip()
    if not model:
        model = profile.default_model
    if not model:
        model = os.getenv("DEFAULT_MODEL", "").strip()
    if not model:
        raise ValueError(
            f"No model configured for Developer {index}. Set "
            f"{specific_prefix}_MODEL, DEVELOPER_MODEL, "
            f"{provider.upper()}_MODEL, or DEFAULT_MODEL in .env."
        )
    return profile.name, model


# ---------------------------------------------------------------------------
# Backward-compatible legacy surface.
# ---------------------------------------------------------------------------

def get_client():
    """Return the default configured provider client.

    Legacy callers previously received a fixed provider client. The provider
    is now resolved from DEFAULT_PROVIDER, so there is no provider-specific
    endpoint or credential embedded in code.
    """
    return get_client_for(os.getenv("DEFAULT_PROVIDER", "").strip() or None)


def ask_ai(prompt: str, system_prompt: str | None = None) -> str:
    """Legacy generic completion using the globally configured model."""
    provider_name, model = resolve_role_llm_spec("developer")
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    response = get_client_for(provider_name).chat.completions.create(
        model=model,
        messages=messages,
    )
    content = response.choices[0].message.content
    return "" if content is None or not str(content).strip() else str(content)
