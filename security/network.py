"""Explicit network egress policy for agent-controlled operations."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


ALLOWED_SCHEMES = frozenset({"https"})
DEFAULT_ALLOWED_HOSTS = frozenset()


def _normalize_host(host: str) -> str:
    """Normalize a hostname for policy comparison."""
    return host.strip().lower().rstrip(".")


def _normalize_schemes(schemes: frozenset[str] | set[str]) -> frozenset[str]:
    """Normalize configured URL schemes for case-insensitive comparison."""
    return frozenset(scheme.strip().lower().rstrip(":") for scheme in schemes)


@dataclass(frozen=True)
class NetworkPolicy:
    """Allow network access only to explicitly approved HTTPS hosts."""

    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS
    allowed_schemes: frozenset[str] = ALLOWED_SCHEMES

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_hosts",
            frozenset(_normalize_host(host) for host in self.allowed_hosts),
        )
        object.__setattr__(
            self,
            "allowed_schemes",
            _normalize_schemes(self.allowed_schemes),
        )

    def validate_url(self, url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")

        normalized_url = url.strip()
        parsed = urlparse(normalized_url)
        scheme = parsed.scheme.lower()
        host = _normalize_host(parsed.hostname or "")

        if scheme not in self.allowed_schemes:
            raise PermissionError(f"Network scheme is not allowed: {scheme or '<missing>'}")
        if not host:
            raise PermissionError("Network URL must include a hostname")
        if host not in self.allowed_hosts:
            raise PermissionError(f"Network destination is not allowed: {host}")
        if parsed.username is not None or parsed.password is not None:
            raise PermissionError("Credential-bearing network URLs are not allowed")

        return normalized_url

    def allows(self, url: str) -> bool:
        try:
            self.validate_url(url)
        except (PermissionError, ValueError):
            return False
        return True


def validate_network_url(
    url: str,
    *,
    allowed_hosts: frozenset[str] | set[str] = DEFAULT_ALLOWED_HOSTS,
) -> str:
    """Validate a URL against an explicit HTTPS host allow-list."""
    policy = NetworkPolicy(allowed_hosts=frozenset(allowed_hosts))
    return policy.validate_url(url)
