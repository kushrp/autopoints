from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from autopoints.api.main import app
from autopoints.api.onboard import (
    AmadeusConfig,
    DiscordConfig,
    GenerateRequest,
    generate,
    is_configured,
    mark_complete,
    sentinel_path,
)
from autopoints.config import settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "autopoints_cache_path", tmp_path / "cache.db")
    monkeypatch.setattr(settings, "amadeus_client_id", "")
    monkeypatch.setattr(settings, "amadeus_client_secret", "")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)


def test_status_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "autopoints_cache_path", tmp_path / "c.db")
    monkeypatch.setattr(settings, "amadeus_client_id", "")
    monkeypatch.setattr(settings, "amadeus_client_secret", "")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    s = is_configured()
    assert s.configured is False
    assert s.amadeus_present is False
    assert s.discord_present is False
    assert s.sentinel_exists is False


def test_status_amadeus_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "autopoints_cache_path", tmp_path / "c.db")
    monkeypatch.setattr(settings, "amadeus_client_id", "abc")
    monkeypatch.setattr(settings, "amadeus_client_secret", "xyz")
    s = is_configured()
    assert s.configured is True
    assert s.amadeus_present is True


def test_status_sentinel(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "autopoints_cache_path", tmp_path / "c.db")
    monkeypatch.setattr(settings, "amadeus_client_id", "")
    monkeypatch.setattr(settings, "amadeus_client_secret", "")
    mark_complete()
    s = is_configured()
    assert s.configured is True
    assert s.sentinel_exists is True


def test_complete_and_reset_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "autopoints_cache_path", tmp_path / "c.db")
    r = client.post("/api/onboard/complete")
    assert r.status_code == 200
    assert sentinel_path().exists()
    r = client.delete("/api/onboard/complete")
    assert r.status_code == 200
    assert not sentinel_path().exists()


def test_index_redirects_when_unconfigured():
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/onboard"


def test_index_renders_spa_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "autopoints_cache_path", tmp_path / "c.db")
    monkeypatch.setattr(settings, "amadeus_client_id", "abc")
    monkeypatch.setattr(settings, "amadeus_client_secret", "xyz")
    r = client.get("/")
    assert r.status_code == 200
    assert "search-form" in r.text


def test_onboard_page_always_accessible():
    r = client.get("/onboard")
    assert r.status_code == 200
    assert "onboard" in r.text.lower()


@respx.mock
def test_amadeus_test_success():
    respx.post("https://test.api.amadeus.com/v1/security/oauth2/token").mock(
        return_value=Response(200, json={"access_token": "tok", "expires_in": 1799})
    )
    r = client.post(
        "/api/onboard/test/amadeus",
        json={"client_id": "abc", "client_secret": "xyz", "hostname": "test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body.get("error") is None


@respx.mock
def test_amadeus_test_invalid_client():
    respx.post("https://test.api.amadeus.com/v1/security/oauth2/token").mock(
        return_value=Response(401, json={"error": "invalid_client"})
    )
    r = client.post(
        "/api/onboard/test/amadeus",
        json={"client_id": "bad", "client_secret": "bad", "hostname": "test"},
    )
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "invalid_client"


@respx.mock
def test_amadeus_test_uses_production_hostname():
    route = respx.post("https://api.amadeus.com/v1/security/oauth2/token").mock(
        return_value=Response(200, json={"access_token": "tok"})
    )
    r = client.post(
        "/api/onboard/test/amadeus",
        json={"client_id": "abc", "client_secret": "xyz", "hostname": "production"},
    )
    assert r.status_code == 200
    assert route.called


@respx.mock
def test_discord_test_success():
    respx.get("https://discord.com/api/v10/users/@me").mock(
        return_value=Response(200, json={"username": "autopoints", "discriminator": "0"})
    )
    r = client.post("/api/onboard/test/discord", json={"token": "MTIz..."})
    body = r.json()
    assert body["ok"] is True
    assert body["bot_username"] == "autopoints"


@respx.mock
def test_discord_test_legacy_discriminator():
    respx.get("https://discord.com/api/v10/users/@me").mock(
        return_value=Response(200, json={"username": "autopoints", "discriminator": "1234"})
    )
    r = client.post("/api/onboard/test/discord", json={"token": "x"})
    assert r.json()["bot_username"] == "autopoints#1234"


@respx.mock
def test_discord_test_unauthorized():
    respx.get("https://discord.com/api/v10/users/@me").mock(
        return_value=Response(401, json={"message": "401: Unauthorized"})
    )
    r = client.post("/api/onboard/test/discord", json={"token": "bad"})
    body = r.json()
    assert body["ok"] is False
    assert "401" in body["error"]


def test_generate_env_local_amadeus_only():
    out = generate(
        GenerateRequest(
            mode="local",
            services=["web"],
            amadeus=AmadeusConfig(enabled=True, client_id="abc", client_secret="xyz"),
        )
    )
    assert "AMADEUS_CLIENT_ID=abc" in out.env
    assert "DISCORD_BOT_TOKEN" not in out.env
    assert out.compose is None


def test_generate_env_nas_with_discord_and_autoruns():
    out = generate(
        GenerateRequest(
            mode="nas",
            services=["web", "discord", "autoruns"],
            amadeus=AmadeusConfig(enabled=True, client_id="aa", client_secret="bb"),
            discord=DiscordConfig(
                enabled=True, token="DISCORD_TOK", guild_id="g1",
                notify_channel_id="c1", run_interval_minutes=30,
            ),
        )
    )
    assert "AMADEUS_CLIENT_ID=aa" in out.env
    assert "DISCORD_BOT_TOKEN=DISCORD_TOK" in out.env
    assert "DISCORD_GUILD_ID=g1" in out.env
    assert "DISCORD_NOTIFY_CHANNEL_ID=c1" in out.env
    assert "DISCORD_RUN_INTERVAL_MINUTES=30" in out.env
    assert "AUTOPOINTS_CACHE_PATH=/data/cache.db" in out.env
    assert out.compose is not None
    assert "ghcr.io/kushrp/autopoints:latest" in out.compose
    assert "autopoints-discord" in out.compose
    assert "watchtower" in out.compose


def test_generate_compose_omits_discord_when_not_selected():
    out = generate(
        GenerateRequest(
            mode="nas",
            services=["web"],
            amadeus=AmadeusConfig(enabled=True, client_id="a", client_secret="b"),
        )
    )
    assert out.compose is not None
    assert "autopoints-discord" not in out.compose
    assert "autopoints-web" in out.compose
    assert "watchtower" in out.compose


def test_generate_endpoint():
    r = client.post(
        "/api/onboard/generate",
        json={
            "mode": "local",
            "services": ["web"],
            "amadeus": {"enabled": True, "client_id": "a", "client_secret": "b", "hostname": "test"},
            "discord": {"enabled": False, "token": "", "guild_id": "", "notify_channel_id": "",
                        "run_interval_minutes": 60, "demo_mode": False},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "AMADEUS_CLIENT_ID=a" in body["env"]
    assert body["compose"] is None
