import os
import threading

import pytest

import config.model as config_model
from config.model import ProviderProfile, RotatingAPIKeyClient, get_client_for


@pytest.fixture(autouse=True)
def _isolate_agnes_keys(monkeypatch):
    """Keep the real .env keys out of every test in this module."""
    for variable in [name for name in os.environ if name.startswith("AGNES_API_KEY")]:
        monkeypatch.delenv(variable, raising=False)
    yield


def profile(monkeypatch, env: dict[str, str]) -> ProviderProfile:
    for variable, value in env.items():
        monkeypatch.setenv(variable, value)
    return ProviderProfile(
        name="agnes",
        api_key_env="AGNES_API_KEY",
        base_url="https://example.test/v1",
        default_model="agnes-2.5-flash",
    )


class FakeCompletions:
    def __init__(self, owner, counter):
        self._owner = owner
        self._counter = counter

    def create(self, **kwargs):
        with self._counter["lock"]:
            self._counter["calls"].append(self._owner["name"])
        return {"model": kwargs.get("model")}


class FakeChat:
    def __init__(self, owner, counter):
        self.completions = FakeCompletions(owner, counter)


class FakeClient:
    def __init__(self, name, counter):
        self._owner = {"name": name}
        self.chat = FakeChat(self._owner, counter)


def counter():
    return {"lock": threading.Lock(), "calls": []}


def test_api_keys_bare_only(monkeypatch):
    assert profile(monkeypatch, {"AGNES_API_KEY": "a"}).api_keys() == ["a"]


def test_api_keys_numbered_are_sorted_across_declaration_order(monkeypatch):
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    assert profile(monkeypatch, {"AGNES_API_KEY3": "c", "AGNES_API_KEY1": "a", "AGNES_API_KEY2": "b"}).api_keys() == ["a", "b", "c"]


def test_api_keys_bare_comes_first_and_deduplicates(monkeypatch):
    assert profile(monkeypatch, {
        "AGNES_API_KEY": "a", "AGNES_API_KEY1": "a", "AGNES_API_KEY2": "b",
    }).api_keys() == ["a", "b"]


def test_api_keys_gaps_are_tolerated_and_blank_ignored(monkeypatch):
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    assert profile(monkeypatch, {
        "AGNES_API_KEY1": "a", "AGNES_API_KEY2": "  ", "AGNES_API_KEY3": "c",
    }).api_keys() == ["a", "c"]


def test_api_keys_empty_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    assert profile(monkeypatch, {}).api_keys() == []


def test_rotation_is_strict_round_robin():
    counter_ = counter()
    clients = [FakeClient(name, counter_) for name in ("k1", "k2", "k3")]
    rotating = RotatingAPIKeyClient(clients)

    for _ in range(7):
        rotating.chat.completions.create(model="m")

    assert counter_["calls"] == ["k1", "k2", "k3", "k1", "k2", "k3", "k1"]
    assert rotating.key_count() == 3


def test_rotation_is_thread_safe_with_exact_distribution():
    counter_ = counter()
    clients = [FakeClient(name, counter_) for name in ("k1", "k2")]
    rotating = RotatingAPIKeyClient(clients)

    def worker():
        for _ in range(25):
            rotating.chat.completions.create(model="m")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert counter_["calls"].count("k1") == 50
    assert counter_["calls"].count("k2") == 50


def test_rotation_requires_at_least_one_client():
    with pytest.raises(ValueError, match="at least one client"):
        RotatingAPIKeyClient([])


def _fresh_clients_cache(monkeypatch):
    monkeypatch.setattr(config_model, "_CLIENTS", {})


def test_get_client_for_rotates_when_multiple_keys_configured(monkeypatch):
    _fresh_clients_cache(monkeypatch)
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.setenv("AGNES_API_KEY1", "k1")
    monkeypatch.setenv("AGNES_API_KEY2", "k2")
    constructed = []

    def fake_openai(api_key, base_url):
        counter_ = {"lock": threading.Lock(), "calls": []}
        client = FakeClient(api_key, counter_)
        constructed.append((api_key, client))
        return client

    monkeypatch.setattr(config_model, "OpenAI", fake_openai)

    client = get_client_for("agnes")
    assert isinstance(client, RotatingAPIKeyClient)
    assert [key for key, _ in constructed] == ["k1", "k2"]

    client.chat.completions.create(model="m")
    client.chat.completions.create(model="m")
    assert constructed[0][1]._owner["name"] == "k1"
    assert constructed[1][1]._owner["name"] == "k2"


def test_get_client_for_single_key_keeps_plain_client(monkeypatch):
    _fresh_clients_cache(monkeypatch)
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.setenv("AGNES_API_KEY1", "only")
    monkeypatch.setattr(config_model, "OpenAI", lambda api_key, base_url: ("plain", api_key))

    client = get_client_for("agnes")
    assert client == ("plain", "only")


def test_get_client_for_without_any_key_raises_runtime_error(monkeypatch):
    _fresh_clients_cache(monkeypatch)
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.delenv("AGNES_API_KEY1", raising=False)
    monkeypatch.delenv("AGNES_API_KEY2", raising=False)
    with pytest.raises(RuntimeError, match="AGNES_API_KEY is not configured"):
        get_client_for("agnes")
