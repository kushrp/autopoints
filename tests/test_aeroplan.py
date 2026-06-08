"""Tests for the v1.c-repaired Aeroplan provider.

Mocks all 3 HTTP layers (Cognito, market-token, air-bounds) with respx so
the unit tests exercise the full handshake without hitting live network.
A @pytest.mark.e2e smoke test against the real backend is intentionally
omitted: production traffic is Kasada-blocked until v1.c-2 routes the call
through Browserbase. See docs/probes/v1c-aeroplan-endpoint-discovery.md.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import httpx
import pytest
import respx

from autopoints.providers.aeroplan import (
    _AIR_BOUNDS_ENDPOINT,
    _COGNITO_ENDPOINT,
    _DEFAULT_API_KEY,
    _MARKET_TOKEN_ENDPOINT,
    AeroplanProvider,
)
from autopoints.providers.base import ProviderError
from autopoints.search.models import Cabin


def _cognito_get_id_response() -> dict[str, Any]:
    """Response shape for AWSCognitoIdentityService.GetId."""
    return {"IdentityId": "us-east-2:fresh-test-identity-id"}


def _cognito_credentials_response() -> dict[str, Any]:
    """Response shape for AWSCognitoIdentityService.GetCredentialsForIdentity."""
    return {
        "IdentityId": "us-east-2:fresh-test-identity-id",
        "Credentials": {
            "AccessKeyId": "ASIA_TEST_KEY",
            "SecretKey": "TEST_SECRET",
            "SessionToken": "TEST_SESSION_TOKEN",
            "Expiration": 1717718400.0,
        },
    }


def _cognito_response() -> dict[str, Any]:
    """Back-compat alias used by older tests. The two-step Cognito flow now
    needs both _cognito_get_id_response and _cognito_credentials_response."""
    return _cognito_credentials_response()


def _mock_cognito_two_step(mock: respx.MockRouter) -> respx.Route:
    """Wire both Cognito calls (GetId then GetCredentialsForIdentity) on the
    same endpoint. Returns the route so tests can assert call_count."""

    def _dispatch(request: httpx.Request) -> httpx.Response:
        target = request.headers.get("X-Amz-Target", "")
        if "GetId" in target:
            return httpx.Response(200, json=_cognito_get_id_response())
        if "GetCredentialsForIdentity" in target:
            return httpx.Response(200, json=_cognito_credentials_response())
        return httpx.Response(400, text=f"unexpected X-Amz-Target: {target}")

    return mock.post(_COGNITO_ENDPOINT).mock(side_effect=_dispatch)


def _market_token_response() -> dict[str, Any]:
    return {"data": {"sessionToken": "ama-test-session-xyz", "expiresIn": 3600}}


def _air_bounds_response_with_one_offer() -> dict[str, Any]:
    return {
        "data": {
            "airBoundGroups": [
                {
                    "boundDetails": {
                        "segments": [
                            {
                                "flight": {"marketingAirlineCode": "AC"},
                                "marketingAirlineCode": "AC",
                            }
                        ]
                    },
                    "airBoundDetails": {
                        "fareFamilies": [
                            {
                                "hierarchy": "eco-saver",
                                "fareFamilyCode": "S1",
                                "pricing": {
                                    "points": 12500,
                                    "totalTaxes": 5.60,
                                    "currencyCode": "CAD",
                                },
                            }
                        ]
                    },
                }
            ]
        }
    }


@pytest.fixture()
def provider() -> AeroplanProvider:
    return AeroplanProvider(client=httpx.AsyncClient(timeout=5.0))


def test_endpoint_constants_match_probe_findings() -> None:
    """Pin the v1.c probe-derived URLs and rotated key so a regression to
    the dead `akamai-akwa-aeroplan` hostname surfaces immediately."""
    assert "akamai-gw.dbaas.aircanada.com" in _AIR_BOUNDS_ENDPOINT
    assert "akamai-gw.dbaas.aircanada.com" in _MARKET_TOKEN_ENDPOINT
    assert "dapidynamicplus" in _AIR_BOUNDS_ENDPOINT
    assert _DEFAULT_API_KEY == "Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm"


def test_search_full_handshake_returns_award_offer(provider: AeroplanProvider) -> None:
    """Happy path: Cognito → market-token → air-bounds → parsed AwardOffer."""
    with respx.mock(assert_all_called=True) as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(
            json=_air_bounds_response_with_one_offer()
        )

        offers = asyncio.run(
            provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
        )

    assert len(offers) == 1
    offer = offers[0]
    assert offer.provider == "AC"
    assert offer.operating_carrier == "AC"
    assert offer.points == 12500
    assert offer.taxes_cents == 560  # 5.60 -> 560 cents
    assert offer.taxes_currency == "CAD"
    assert offer.fare_class == "S1"


def test_air_bounds_request_carries_ama_headers(provider: AeroplanProvider) -> None:
    """The final request must include ama-client-ref + ama-session-token from
    the market-token response, plus x-api-key. Missing any of these returns
    401/403/Kasada-block in production."""
    seen_headers: dict[str, str] = {}

    def capture_air_bounds(request: httpx.Request) -> httpx.Response:
        seen_headers.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(200, json=_air_bounds_response_with_one_offer())

    with respx.mock() as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).mock(side_effect=capture_air_bounds)

        asyncio.run(provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy))

    assert seen_headers["x-api-key"] == _DEFAULT_API_KEY
    assert seen_headers["ama-session-token"] == "ama-test-session-xyz"
    assert "ama-client-ref" in seen_headers
    # ama-client-ref is a UUID — assert shape rather than value.
    assert len(seen_headers["ama-client-ref"]) >= 32


def test_market_token_request_is_sigv4_signed(provider: AeroplanProvider) -> None:
    """The market-token POST must carry an Authorization header produced by
    SigV4Auth — proves the Cognito credentials were threaded through."""
    seen_headers: dict[str, str] = {}

    def capture_market_token(request: httpx.Request) -> httpx.Response:
        seen_headers.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(200, json=_market_token_response())

    with respx.mock() as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).mock(side_effect=capture_market_token)
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(
            json=_air_bounds_response_with_one_offer()
        )

        asyncio.run(provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy))

    assert "authorization" in seen_headers
    auth = seen_headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256")
    assert "Credential=ASIA_TEST_KEY/" in auth
    assert "execute-api" in auth
    assert "us-east-2" in auth


def test_kasada_429_on_market_token_raises_actionable_error(
    provider: AeroplanProvider,
) -> None:
    """Production market-token responds 429 (Kasada). Error must point at
    v1.c-2 follow-up so an operator knows the next step."""
    with respx.mock() as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(
            429, headers={"x-kpsdk-ct": "test"}, text="blocked"
        )

        with pytest.raises(ProviderError) as exc:
            asyncio.run(
                provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
            )

    assert "Kasada" in str(exc.value)
    assert "v1.c-2" in str(exc.value)


def test_kasada_429_on_air_bounds_raises_actionable_error(
    provider: AeroplanProvider,
) -> None:
    """Same fallback path for the air-bounds call."""
    with respx.mock() as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(429, text="blocked")

        with pytest.raises(ProviderError) as exc:
            asyncio.run(
                provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
            )

    assert "Kasada" in str(exc.value)


def test_cognito_failure_surfaces_provider_error(provider: AeroplanProvider) -> None:
    with respx.mock() as mock:
        mock.post(_COGNITO_ENDPOINT).respond(503, text="cognito down")

        with pytest.raises(ProviderError, match="Cognito"):
            asyncio.run(
                provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
            )


def test_air_bounds_401_points_at_rotated_key(provider: AeroplanProvider) -> None:
    """A 401/403 on air-bounds means the rotated x-api-key has rotated again.
    Error must reference the probe doc so the next dev can re-discover it."""
    with respx.mock() as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(401, text="bad key")

        with pytest.raises(ProviderError, match="api_key may"):
            asyncio.run(
                provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
            )


def test_parser_skips_unparseable_fare_rows(provider: AeroplanProvider) -> None:
    """If a fare row is missing pricing fields, skip it but keep the rest."""
    payload = {
        "data": {
            "airBoundGroups": [
                {
                    "boundDetails": {
                        "segments": [{"marketingAirlineCode": "UA"}]
                    },
                    "airBoundDetails": {
                        "fareFamilies": [
                            {"hierarchy": "eco", "pricing": {}},  # bad
                            {
                                "hierarchy": "eco-flex",
                                "fareFamilyCode": "F1",
                                "pricing": {
                                    "points": 25000,
                                    "totalTaxes": 11.20,
                                    "currencyCode": "CAD",
                                },
                            },
                        ]
                    },
                }
            ]
        }
    }
    with respx.mock() as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(json=payload)

        offers = asyncio.run(
            provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
        )

    assert len(offers) == 1
    assert offers[0].points == 25000


def test_use_browserbase_raises_when_creds_missing() -> None:
    """Without BROWSERBASE_API_KEY/PROJECT_ID, the Browserbase path raises
    with a clear 'not configured' message from the _browserbase helper."""
    provider = AeroplanProvider(use_browserbase=True, client=httpx.AsyncClient(timeout=5.0))

    # Force empty Browserbase creds so get_session() raises ProviderError.
    from autopoints.config import Settings
    import autopoints.providers._browserbase as bb_module

    empty_settings = Settings(
        browserbase_api_key="",
        browserbase_project_id="",
    )
    original_settings = bb_module.default_settings
    bb_module.default_settings = empty_settings
    try:
        with pytest.raises(ProviderError, match="Browserbase not configured"):
            asyncio.run(
                provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
            )
    finally:
        bb_module.default_settings = original_settings


def test_browserbase_path_runs_full_flow_with_mocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end v1.c-2 path with the Browserbase session + page fully
    mocked. Verifies the orchestration sequence:
    1. get_session() called
    2. page.goto navigates to a Kasada-protected aircanada.com page
    3. Cognito creds fetched server-side (httpx)
    4. market-token signed and fired via page.evaluate (in-page fetch)
    5. air-bounds fired via page.evaluate (in-page fetch)
    6. browser.close() called even on exception
    """

    class FakePage:
        def __init__(self) -> None:
            self.goto_calls: list[str] = []
            self.evaluate_calls: list[tuple[str, dict[str, Any]]] = []

        async def goto(self, url: str, **_kw: Any) -> None:
            self.goto_calls.append(url)

        async def wait_for_timeout(self, _ms: int) -> None:
            pass

        async def evaluate(self, script: str, arg: dict[str, Any]) -> dict[str, Any]:
            self.evaluate_calls.append((script, arg))
            if arg["url"] == _MARKET_TOKEN_ENDPOINT:
                return {
                    "status": 200,
                    "body": json.dumps(
                        {"data": {"sessionToken": "ama-test-session-from-browser"}}
                    ),
                }
            if arg["url"] == _AIR_BOUNDS_ENDPOINT:
                return {
                    "status": 200,
                    "body": json.dumps(_air_bounds_response_with_one_offer()),
                }
            raise AssertionError(f"unexpected URL: {arg['url']}")

    class FakeBrowser:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    fake_page = FakePage()
    fake_browser = FakeBrowser()

    async def fake_get_session(**_kw: Any) -> tuple[FakePage, FakeBrowser]:
        return fake_page, fake_browser

    import autopoints.providers._browserbase as bb_module

    monkeypatch.setattr(bb_module, "get_session", fake_get_session)

    provider = AeroplanProvider(use_browserbase=True, client=httpx.AsyncClient(timeout=5.0))
    with respx.mock() as mock:
        # Cognito is still hit server-side (it's not Kasada-protected).
        _mock_cognito_two_step(mock)

        offers = asyncio.run(
            provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
        )

    assert len(offers) == 1
    assert offers[0].points == 12500
    assert fake_browser.closed is True, "browser must be closed to release Browserbase session"
    # Navigation to aircanada.com happened before any API calls.
    assert any("aircanada.com" in url for url in fake_page.goto_calls)
    # Both market-token and air-bounds were fired in-page.
    evaluated_urls = {arg["url"] for _script, arg in fake_page.evaluate_calls}
    assert _MARKET_TOKEN_ENDPOINT in evaluated_urls
    assert _AIR_BOUNDS_ENDPOINT in evaluated_urls


def test_browserbase_path_closes_browser_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the air-bounds fetch fails, the browser is still closed —
    leaked Browserbase sessions cost real money."""

    class FakePage:
        async def goto(self, *_a: Any, **_kw: Any) -> None:
            pass

        async def wait_for_timeout(self, _ms: int) -> None:
            pass

        async def evaluate(self, _script: str, _arg: dict[str, Any]) -> dict[str, Any]:
            return {"status": 503, "body": "kasada solved but server fried"}

    class FakeBrowser:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    fake_browser = FakeBrowser()

    async def fake_get_session(**_kw: Any) -> tuple[FakePage, FakeBrowser]:
        return FakePage(), fake_browser

    import autopoints.providers._browserbase as bb_module

    monkeypatch.setattr(bb_module, "get_session", fake_get_session)

    provider = AeroplanProvider(use_browserbase=True, client=httpx.AsyncClient(timeout=5.0))
    with respx.mock() as mock:
        _mock_cognito_two_step(mock)

        with pytest.raises(ProviderError):
            asyncio.run(
                provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
            )

    assert fake_browser.closed is True


@pytest.mark.e2e
def test_live_aeroplan_via_browserbase_jfk_yyz() -> None:
    """Smoke test against the real Air Canada Aeroplan backend via
    Browserbase. Marked e2e so the default suite skips it. Requires:
    - BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID set in env
    - A live (not-revoked) Cognito IdentityId hardcoded in aeroplan.py
    - `pip install browserbase playwright && playwright install chromium`

    Asserts: search returns >=1 AwardOffer for a known partner-rich route.
    """
    from autopoints.config import settings

    if not settings.browserbase_api_key or not settings.browserbase_project_id:
        pytest.skip("BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID not set")

    provider = AeroplanProvider(use_browserbase=True)
    depart = date.today() + __import__("datetime").timedelta(days=60)
    offers = asyncio.run(provider.search("JFK", "YYZ", depart, Cabin.economy))
    assert len(offers) >= 1, "expected at least one Aeroplan award offer"
    assert offers[0].points > 0
    assert offers[0].taxes_currency in ("CAD", "USD")


def test_empty_air_bounds_returns_empty_list(provider: AeroplanProvider) -> None:
    with respx.mock() as mock:
        _mock_cognito_two_step(mock)
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(
            json={"data": {"airBoundGroups": []}}
        )

        offers = asyncio.run(
            provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
        )

    assert offers == []
