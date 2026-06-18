from __future__ import annotations

import pytest

from autopoints.auth.guardrails import (
    AntiBanGuard,
    DailyCapExceeded,
    DisallowedRequest,
    Frozen,
    RateLimited,
)
from autopoints.auth.op_client import OnePasswordClient
from autopoints.auth.preflight import preflight
from autopoints.auth.session_manager import SessionManager
from autopoints.auth.session_store import SessionBlob, SessionStore, redacted


class FakeBackend:
    """In-memory CredentialBackend for testing the spine without `op`."""

    def __init__(self) -> None:
        self.fields = {("aeroplan", "username"): "me@example.com", ("aeroplan", "password"): "pw"}
        self.otps = {"aeroplan": "123456"}
        self.notes: dict[str, str] = {}

    def get_field(self, item: str, field: str) -> str:
        return self.fields[(item, field)]

    def get_otp(self, item: str) -> str | None:
        return self.otps.get(item)

    def read_note(self, title: str) -> str | None:
        return self.notes.get(title)

    def write_note(self, title: str, body: str) -> None:
        self.notes[title] = body


def _blob(program: str = "aeroplan") -> SessionBlob:
    return SessionBlob(
        program=program,
        captured_at="2026-06-17T00:00:00Z",
        expires_at_hint="2026-06-24",
        storage_state={"cookies": [{"name": "sid", "value": "abc"}]},
        additional_headers={"x-api-key": "k"},
    )


def test_op_client_credentials_and_otp():
    client = OnePasswordClient(FakeBackend())
    creds = client.credentials("aeroplan")
    assert creds.username == "me@example.com" and creds.password == "pw"
    assert client.otp("aeroplan") == "123456"


def test_session_store_round_trip():
    store = SessionStore(FakeBackend())
    store.save(_blob())
    loaded = store.load("aeroplan")
    assert loaded is not None
    assert loaded.storage_state["cookies"][0]["value"] == "abc"
    assert loaded.additional_headers == {"x-api-key": "k"}


def test_session_store_missing_returns_none():
    assert SessionStore(FakeBackend()).load("united") is None


def test_redacted_hides_secrets():
    r = redacted(_blob())
    assert r["storage_state"] == "<redacted>" and r["additional_headers"] == "<redacted>"
    assert r["program"] == "aeroplan"


def test_session_manager_caches_and_refreshes():
    store = SessionStore(FakeBackend())
    calls = {"n": 0}

    def login(program: str) -> SessionBlob:
        calls["n"] += 1
        return _blob(program)

    mgr = SessionManager(store, login)
    assert mgr.get("aeroplan") is None  # nothing stored yet
    session = mgr.refresh("aeroplan")  # login fires, persists, caches
    assert calls["n"] == 1
    assert session.cookies() == {"sid": "abc"}
    assert mgr.get("aeroplan") is session  # served from cache, no second login
    assert calls["n"] == 1
    mgr.invalidate("aeroplan")
    assert mgr.get("aeroplan") is not None  # re-read from store
    assert calls["n"] == 1  # store read, not a re-login


def test_guard_url_and_method_gates():
    g = AntiBanGuard("aeroplan", allowed_url_prefixes=("https://akamai-gw.dbaas.aircanada.com/",))
    g.check_url("https://akamai-gw.dbaas.aircanada.com/loyalty/air-bounds")
    with pytest.raises(DisallowedRequest):
        g.check_url("https://aircanada.com/book/checkout")
    with pytest.raises(DisallowedRequest):
        g.check_method("DELETE")
    g.check_method("post")  # case-insensitive, allowed


def test_guard_rate_limit_and_release():
    t = {"v": 1000.0}
    g = AntiBanGuard("aeroplan", allowed_url_prefixes=(), now=lambda: t["v"], rng=lambda: 0.0)
    g.acquire()
    g.release()
    with pytest.raises(RateLimited):  # 61s gap not yet elapsed (min 60s)
        t["v"] = 1050.0
        g.acquire()
    t["v"] = 1061.0
    g.acquire()  # past the 60s window


def test_guard_daily_cap():
    t = {"v": 0.0}
    g = AntiBanGuard("a", allowed_url_prefixes=(), daily_cap=2, now=lambda: t["v"], rng=lambda: 0.0)
    g.acquire()
    g.release()
    t["v"] += 100
    g.acquire()
    g.release()
    t["v"] += 100
    with pytest.raises(DailyCapExceeded):
        g.acquire()


def test_guard_auto_freeze_on_hostile_response():
    t = {"v": 0.0}
    g = AntiBanGuard("a", allowed_url_prefixes=(), now=lambda: t["v"], rng=lambda: 0.0)
    g.acquire()
    g.release()
    g.note_response(429)
    assert g.is_frozen
    t["v"] += 100
    with pytest.raises(Frozen):
        g.acquire()


def test_preflight_reports_missing(monkeypatch):
    monkeypatch.delenv("OP_CONNECT_HOST", raising=False)
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    result = preflight()
    assert "Browserbase" in result.report()
    assert isinstance(result.ready, bool)
