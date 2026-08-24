"""Multi-provider LLM configuration with per-role model bindings.

Layered design:

1. ``ProviderProfile`` - connection facts for one OpenAI-compatible
   endpoint (credential env var, base URL, default model).
2. Role bindings - each team role resolves to ``(provider, model)`` via
   ``{ROLE}_PROVIDER`` / ``{ROLE}_MODEL`` environment variables, falling
   back to ``DEFAULT_PROVIDER`` and the profile's default model.
3. Lazy clients - one cached client per profile, constructed on first
   actual use. Importing this module stays side-effect free.

Backward compatibility: ``get_client()`` keeps its original meaning
(the Agnes client) for legacy callers such as ``ask_ai``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


# Legacy Agnes constants kept for backward-compatible imports elsewhere.
# Values are pure environment reads — no endpoint/model literals in code.
AGNES_BASE_URL = os.getenv("AGNES_BASE_URL")
AGNES_MODEL = os.getenv("AGNES_MODEL")


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
    default_base_url: str
    default_model: str

    def api_key(self) -> str | None:
        """Read the credential from the *current* environment."""
        return os.getenv(self.api_key_env)


def declared_provider_names() -> list[str]:
    """Return all usable provider profile names, order-stable.

    Two sources, merged:

    1. ``LLM_PROVIDERS`` — explicit comma-separated declaration;
    2. auto-discovery — any environment variable named ``<X>_API_KEY``
       implicitly declares provider ``x``.
    """
    import re

    names: list[str] = []
    seen: set[str] = set()

    raw = os.getenv("LLM_PROVIDERS", "")
    for item in raw.split(","):
        name = item.strip().lower()
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    pattern = re.compile(r"^([A-Z0-9]+)_API_KEY$")
    for var in os.environ:
        m = pattern.match(var)
        if m:
            name = m.group(1).lower()
            if name not in seen:
                seen.add(name)
                names.append(name)

    return names


def get_provider_profile(name: str | None = None) -> ProviderProfile:
    """Resolve a provider profile by name (default: first declared).

    Profiles are built dynamically from the current environment:

    - credential: ``{NAME}_API_KEY``   (required at call time)
    - base URL:   ``{NAME}_BASE_URL``  (required)
    - model:      ``{NAME}_MODEL``     (optional)

    There are NO built-in providers in code — everything lives in `.env`.
    """
    key = str(name if name is not None else _first_declared_provider())
    key = key.strip().lower()

    prefix = key.upper()
    api_key_env = f"{prefix}_API_KEY"
    base_url = os.getenv(f"{prefix}_BASE_URL")
    if base_url is None:
        available = ", ".join(declared_provider_names()) or "(none)"
        raise ValueError(
            f"Unknown provider profile: {key!r}. "
            f"Set {prefix}_API_KEY + {prefix}_BASE_URL + optional "
            f"{prefix}_MODEL in the environment, or use one of: {available}"
        )

    return ProviderProfile(
        name=key,
        api_key_env=api_key_env,
        default_base_url=base_url,
        default_model=os.getenv(f"{prefix}_MODEL", ""),
    )


def _first_declared_provider() -> str:
    names = declared_provider_names()
    if not names:
        raise ValueError(
            "No LLM providers configured. Declare at least one in the "
            "environment, e.g.: OPENROUTER_API_KEY=... + "
            "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1"
        )
    return names[0]


def get_client_for(profile_name: str | None = None):
    """Return the cached client for one profile, constructing it lazily.

    Importing this module remains side-effect free: credential validation
    and client construction happen on first actual use.
    """
    profile = get_provider_profile(profile_name)

    cached = _CLIENTS.get(profile.name)
    if cached is None:
        api_key = profile.api_key()
        if not api_key:
            raise RuntimeError(
                f"{profile.api_key_env} is not configured."
            )
        base_url_override = os.getenv(f"{profile.name.upper()}_BASE_URL")
        cached = OpenAI(
            api_key=api_key,
            base_url=(
                base_url_override
                if base_url_override
                else profile.default_base_url
            ),
        )
        _CLIENTS[profile.name] = cached
    return cached


_CLIENTS: dict[str, Any] = {}


def resolve_role_llm_spec(role: str) -> tuple[str, str]:
    """Resolve ``(provider_profile_name, model_id)`` for one team role.

    Resolution order for the model: ``{ROLE}_MODEL`` environment variable,
    then the bound provider profile's default model. The provider itself
    comes from ``{ROLE}_PROVIDER``, falling back to ``DEFAULT_PROVIDER``.
    """
    if role not in SUPPORTED_ROLES:
        raise ValueError(
            f"Unknown role: {role!r}. Supported: {SUPPORTED_ROLES}"
        )

    prefix = role.upper()
    provider_name = os.getenv(
        f"{prefix}_PROVIDER",
        os.getenv("DEFAULT_PROVIDER", "agnes"),
    ).strip().lower()

    profile = get_provider_profile(provider_name)

    model = os.getenv(f"{prefix}_MODEL", "").strip()
    if not model:
        model = profile.default_model

    return profile.name, model


def _resolve_default_client_profile() -> str:
    """Legacy hook: the plain ``get_client`` is pinned to the Agnes profile."""
    return "agnes"


# ---------------------------------------------------------------------------
# Legacy Agnes-only surface (unchanged behavior for existing callers).
# ---------------------------------------------------------------------------

_client: Any = None


def get_client():
    """Return the shared Agnes client, constructing it lazily.

    Kept for backward compatibility: new code should prefer
    :func:`get_client_for` with an explicit provider profile.
    """
    global _client
    if _client is None:
        api_key = os.getenv("AGNES_API_KEY")
        if not api_key:
            raise RuntimeError(
                "AGNES_API_KEY is not configured."
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("AGNES_BASE_URL", AGNES_BASE_URL),
        )
    return _client


def ask_ai(
    prompt: str,
    system_prompt: str | None = None,
) -> str:
    messages = []

    if system_prompt:
        messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )

    messages.append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    response = get_client().chat.completions.create(
        model=AGNES_MODEL,
        messages=messages,
    )

    return response.choices[0].message.content or ""
