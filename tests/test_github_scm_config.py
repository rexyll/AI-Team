from __future__ import annotations

import pytest

from runtime.github_scm_config import (
    GitHubSCMConfigurationError,
    create_github_scm_runtime,
)


class FakeTransport:
    def request(self, method, path, payload=None):
        return {}


def _environment(**overrides):
    values = {
        "AI_TEAM_GITHUB_TOKEN": "ghp-test-secret-value",
        "AI_TEAM_GITHUB_REPOSITORY": "acme/widget",
        "AI_TEAM_GITHUB_PULL_REQUEST": "12",
    }
    values.update(overrides)
    return values


def test_github_scm_is_disabled_without_host_configuration():
    assert create_github_scm_runtime(environ={}) is None


@pytest.mark.parametrize(
    "environment",
    [
        {"AI_TEAM_GITHUB_REPOSITORY": "acme/widget"},
        {"AI_TEAM_GITHUB_PULL_REQUEST": "12"},
        {
            "AI_TEAM_GITHUB_REPOSITORY": "acme/widget",
            "AI_TEAM_GITHUB_PULL_REQUEST": "12",
        },
    ],
)
def test_partial_configuration_fails_closed(environment):
    with pytest.raises(GitHubSCMConfigurationError):
        create_github_scm_runtime(environ=environment)


def test_factory_requires_token_when_observation_is_enabled():
    environment = _environment()
    environment.pop("AI_TEAM_GITHUB_TOKEN")

    with pytest.raises(GitHubSCMConfigurationError, match="AI_TEAM_GITHUB_TOKEN"):
        create_github_scm_runtime(environ=environment)


@pytest.mark.parametrize(
    ("repository", "pull_request"),
    [
        ("../widget", "12"),
        ("acme/widget", "0"),
        ("acme/widget", "-1"),
        ("acme/widget", "1.5"),
        ("acme/widget", "abc"),
    ],
)
def test_factory_rejects_invalid_repository_or_pull_request(repository, pull_request):
    environment = _environment(
        AI_TEAM_GITHUB_REPOSITORY=repository,
        AI_TEAM_GITHUB_PULL_REQUEST=pull_request,
    )

    with pytest.raises(GitHubSCMConfigurationError):
        create_github_scm_runtime(
            environ=environment,
            transport_factory=lambda token: FakeTransport(),
        )


def test_factory_keeps_token_out_of_runtime_representation():
    secret = "ghp-do-not-print-this"
    captured = []
    runtime = create_github_scm_runtime(
        environ=_environment(AI_TEAM_GITHUB_TOKEN=secret),
        transport_factory=lambda token: (captured.append(token) or FakeTransport()),
    )

    assert runtime is not None
    assert captured == [secret]
    assert secret not in repr(runtime)
    assert runtime.repository == "acme/widget"
    assert runtime.pull_request_number == 12
    assert "service=" not in repr(runtime)
