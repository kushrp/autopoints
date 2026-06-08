"""Tests for the v1.c-repaired Aeroplan provider.

Mocks all 3 HTTP layers (Cognito, market-token, air-bounds) with respx so
the unit tests exercise the full handshake without hitting live network.
A @pytest.mark.e2e smoke test against the real backend is intentionally
omitted: production traffic is Kasada-blocked until v1.c-2 routes the call
through Browserbase. See docs/probes/v1c-aeroplan-endpoint-discovery.md.
"""

from __future__ import annotations

import asyncio
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


def _cognito_response() -> dict[str, Any]:
    return {
        "IdentityId": "us-east-2:7f9c31d7-d242-4f7e-afda-916b8c6c2b9c",
        "Credentials": {
            "AccessKeyId": "ASIA_TEST_KEY",
            "SecretKey": "TEST_SECRET",
            "SessionToken": "TEST_SESSION_TOKEN",
            "Expiration": 1717718400.0,
        },
    }


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
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
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
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
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
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
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
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
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
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
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
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
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
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(json=payload)

        offers = asyncio.run(
            provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
        )

    assert len(offers) == 1
    assert offers[0].points == 25000


def test_use_browserbase_scaffold_raises_actionable_error() -> None:
    """v1.c-2 scaffold: use_browserbase=True is the documented Kasada-bypass
    path but the wiring isn't done. Verify it raises with a clear pointer to
    the probe doc + the implementation outline."""
    provider = AeroplanProvider(use_browserbase=True, client=httpx.AsyncClient(timeout=5.0))
    with pytest.raises(ProviderError) as exc:
        asyncio.run(
            provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
        )
    msg = str(exc.value)
    assert "Browserbase" in msg
    assert "v1.c-2" in msg
    assert "Kasada" in msg


def test_use_browserbase_skips_cognito_and_market_token() -> None:
    """When use_browserbase=True, the direct-HTTP Cognito + market-token
    handshake is skipped — the in-page fetch (v1.c-2) handles auth itself."""
    provider = AeroplanProvider(use_browserbase=True, client=httpx.AsyncClient(timeout=5.0))
    with respx.mock(assert_all_called=False) as mock:
        # Set up cognito + market-token routes that would be hit by the
        # direct path. With use_browserbase=True, they should NOT be called.
        cognito_route = mock.post(_COGNITO_ENDPOINT)
        market_route = mock.post(_MARKET_TOKEN_ENDPOINT)

        with pytest.raises(ProviderError):
            asyncio.run(
                provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
            )

    assert cognito_route.call_count == 0
    assert market_route.call_count == 0


def test_empty_air_bounds_returns_empty_list(provider: AeroplanProvider) -> None:
    with respx.mock() as mock:
        mock.post(_COGNITO_ENDPOINT).respond(json=_cognito_response())
        mock.post(_MARKET_TOKEN_ENDPOINT).respond(json=_market_token_response())
        mock.post(_AIR_BOUNDS_ENDPOINT).respond(
            json={"data": {"airBoundGroups": []}}
        )

        offers = asyncio.run(
            provider.search("JFK", "YYZ", date(2026, 10, 15), Cabin.economy)
        )

    assert offers == []
