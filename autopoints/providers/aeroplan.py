"""Air Canada Aeroplan live award search.

**Status (2026-06-08):** endpoint re-discovered and handshake implemented.
The original `akamai-akwa-aeroplan.aircanada.com` hostname is NXDOMAIN; the
live backend has moved to `akamai-gw.dbaas.aircanada.com` and gained a
multi-step AWS Cognito + SigV4 + market-token handshake. See
``docs/probes/v1c-aeroplan-endpoint-discovery.md`` for the full reverse
engineering write-up.

**What works:** the URL + handshake are correct against public scrapers
(``RiskByPass/riskbypass_demo``, ``xmsley614/nt_tool``, others). Tests use
``respx`` to mock all three HTTP layers.

**What's still gated:** the production endpoint sits behind Kasada bot
management (HTTP 429 + ``x-kpsdk-ct`` headers). A server-side signed request
will be Kasada-blocked. The phase-2 follow-up (v1.c-2) routes the
``air-bounds`` POST through ``autopoints/providers/_browserbase.py`` so a
real Chrome session solves the Kasada challenge and the JSON is intercepted
the way ``lg/awardwiz`` did with Arkalis. Until then, ``--live-aeroplan``
will raise ``ProviderError`` on production traffic; the static-chart
provider remains the safety net.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import httpx

from autopoints.providers.base import AwardProvider, ProviderError
from autopoints.search.models import AwardOffer, Cabin

# Updated 2026-06-08 per docs/probes/v1c-aeroplan-endpoint-discovery.md.
_HOST = "akamai-gw.dbaas.aircanada.com"
_AIR_BOUNDS_ENDPOINT = (
    f"https://{_HOST}/loyalty/dapidynamicplus/1ASIUDALAC/v2/search/air-bounds"
)
_MARKET_TOKEN_ENDPOINT = (
    f"https://{_HOST}/loyalty/dapidynamicplus/1ASIUDALAC/v2/reward/market-token"
)
_COGNITO_ENDPOINT = "https://cognito-identity.us-east-2.amazonaws.com/"

# Cognito identity used by aircanada.com's public web client. This is not
# a credential — it's the unauthenticated identity pool ID the booking
# widget itself uses to obtain ephemeral AWS creds for SigV4 signing.
_COGNITO_IDENTITY_ID = "us-east-2:7f9c31d7-d242-4f7e-afda-916b8c6c2b9c"

# Rotated 2026-06-08 (was 1ASIUDALAC). The 1ASIUDALAC in the URL path is
# a separate market/tenant code and stays in the path.
_DEFAULT_API_KEY = "Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm"

_AWS_REGION = "us-east-2"
_AWS_SERVICE = "execute-api"

_CABIN_MAP = {
    Cabin.economy: "eco",
    Cabin.premium_economy: "ecoPremium",
    Cabin.business: "business",
    Cabin.first: "first",
}


class AeroplanProvider(AwardProvider):
    name = "aeroplan"
    program_code = "AC"

    def __init__(
        self,
        api_key: str = _DEFAULT_API_KEY,
        client: httpx.AsyncClient | None = None,
        use_browserbase: bool = False,
    ):
        """
        Args:
            api_key: x-api-key for the Aeroplan endpoint (rotated 2026-06-08).
            client: httpx.AsyncClient for the direct-HTTP path (v1.c-1).
            use_browserbase: when True, route the air-bounds call through a
                real Chrome session via `autopoints/providers/_browserbase.py`
                so Kasada bot management is solved by the browser challenge.
                This is the v1.c-2 path (see plan). Default False because
                Browserbase usage costs money and requires API key + project
                ID in Settings.
        """
        self._api_key = api_key
        self._use_browserbase = use_browserbase
        self._client = client or httpx.AsyncClient(
            timeout=20.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.aircanada.com",
                "Referer": "https://www.aircanada.com/",
            },
        )

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[AwardOffer]:
        body = self._build_search_body(origin, destination, depart_date, passengers)
        if self._use_browserbase:
            return await self._search_via_browserbase(
                body, origin, destination, depart_date, cabin
            )
        creds = await self._get_cognito_credentials()
        session_token = await self._get_market_token(creds)
        return await self._search_air_bounds(
            body, session_token, origin, destination, depart_date, cabin
        )

    async def _search_via_browserbase(
        self,
        body: dict[str, Any],
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
    ) -> list[AwardOffer]:
        """v1.c-2 Kasada-bypass path. Not yet implemented end-to-end.

        Outline (per docs/probes/v1c-aeroplan-endpoint-discovery.md §5):

        1. Open a Browserbase session via `_browserbase.get_session()`. A real
           Chrome instance solves the Kasada x-kpsdk-ct/x-kpsdk-r challenge
           on first navigation to a Kasada-protected aircanada.com page.
        2. Navigate to https://www.aircanada.com/ and wait for Kasada cookies
           (`x-kpsdk-cd`) to set on the context. ~3-5 second wait.
        3. Within the Chrome context, fire the air-bounds POST via
           `page.evaluate(fetch_script)` so the request carries the Kasada
           cookies the challenge produced. The fetch script also:
           - Performs the Cognito + SigV4 + market-token preflight inside the
             page (so signing uses the same TLS fingerprint that solved Kasada)
           - Or, more cheaply, runs them server-side and passes the
             session_token in to the in-page fetch
        4. Intercept the response via `page.expect_response("**/air-bounds")`
           and parse the JSON with the same `_parse_air_bounds` helper.

        Status: scaffold only. Requires a live Browserbase API key + project ID
        in Settings (already added to `autopoints/config.py:Settings` in v0).
        Tests for this path are gated on @pytest.mark.e2e + the Browserbase
        creds being present.
        """
        raise ProviderError(
            "Aeroplan via Browserbase: not yet implemented (v1.c-2). "
            "See docs/probes/v1c-aeroplan-endpoint-discovery.md §5 for the "
            "Kasada bypass sequence. Set use_browserbase=False (default) for "
            "the direct-HTTP path, which works against any non-Kasada "
            "deployment of the endpoint (e.g. mocked tests, residential "
            "proxy + custom Kasada solver)."
        )

    async def _get_cognito_credentials(self) -> dict[str, str]:
        """Step 1: exchange the hard-coded IdentityId for ephemeral AWS creds.

        The Cognito identity pool is unauthenticated and shared with the
        aircanada.com public web client. Returns dict with AccessKeyId,
        SecretKey, SessionToken.
        """
        try:
            resp = await self._client.post(
                _COGNITO_ENDPOINT,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "AWSCognitoIdentityService.GetCredentialsForIdentity",
                },
                json={"IdentityId": _COGNITO_IDENTITY_ID},
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"Aeroplan: Cognito identity exchange failed: {e}") from e
        if resp.status_code != 200:
            raise ProviderError(
                f"Aeroplan: Cognito returned {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()["Credentials"]
        except (KeyError, ValueError) as e:
            raise ProviderError(
                f"Aeroplan: Cognito response missing Credentials: {e}"
            ) from e

    async def _get_market_token(self, creds: dict[str, str]) -> str:
        """Step 2: SigV4-sign a POST to the market-token endpoint; return
        the sessionToken needed by air-bounds.
        """
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            from botocore.credentials import Credentials
        except ImportError as e:
            raise ProviderError(
                "Aeroplan: botocore is required for SigV4 signing — "
                "add 'botocore' to dependencies. Run `uv pip install botocore`."
            ) from e

        aws_creds = Credentials(
            access_key=creds["AccessKeyId"],
            secret_key=creds["SecretKey"],
            token=creds.get("SessionToken"),
        )
        market_body = b"{}"
        aws_req = AWSRequest(
            method="POST",
            url=_MARKET_TOKEN_ENDPOINT,
            data=market_body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
            },
        )
        SigV4Auth(aws_creds, _AWS_SERVICE, _AWS_REGION).add_auth(aws_req)

        try:
            resp = await self._client.post(
                _MARKET_TOKEN_ENDPOINT,
                headers=dict(aws_req.headers.items()),
                content=market_body,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"Aeroplan: market-token request failed: {e}") from e
        if resp.status_code == 429:
            raise ProviderError(
                "Aeroplan: market-token returned 429 (Kasada bot challenge). "
                "Phase 2 (v1.c-2) wires this call through Browserbase to solve "
                "the Kasada challenge; see docs/probes/v1c-aeroplan-endpoint-discovery.md."
            )
        if resp.status_code != 200:
            raise ProviderError(
                f"Aeroplan: market-token returned {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()["data"]["sessionToken"]
        except (KeyError, ValueError) as e:
            raise ProviderError(
                f"Aeroplan: market-token response missing data.sessionToken: {e}"
            ) from e

    @staticmethod
    def _build_search_body(
        origin: str,
        destination: str,
        depart_date: date,
        passengers: int,
    ) -> dict[str, Any]:
        return {
            "bookingCodes": ["X", "I", "O", "R"],  # Aeroplan award fare buckets
            "passengers": {
                "adults": passengers,
                "youth": 0,
                "children": 0,
                "infants": 0,
            },
            "bounds": [
                {
                    "originLocationCode": origin.upper(),
                    "destinationLocationCode": destination.upper(),
                    "departureDate": depart_date.isoformat(),
                }
            ],
            "isFlexibleSearch": False,
            "searchPreferences": {"showSoldOut": False},
        }

    async def _search_air_bounds(
        self,
        body: dict[str, Any],
        session_token: str,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
    ) -> list[AwardOffer]:
        """Step 3: POST air-bounds with the session token + ama-client-ref
        headers. Returns parsed AwardOffers.
        """
        try:
            resp = await self._client.post(
                _AIR_BOUNDS_ENDPOINT,
                headers={
                    "x-api-key": self._api_key,
                    "ama-client-ref": str(uuid.uuid4()),
                    "ama-session-token": session_token,
                },
                json=body,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"Aeroplan air-bounds request failed: {e}") from e

        if resp.status_code == 429:
            raise ProviderError(
                "Aeroplan: air-bounds returned 429 (Kasada bot challenge). "
                "Phase 2 (v1.c-2) routes this call through Browserbase; see "
                "docs/probes/v1c-aeroplan-endpoint-discovery.md."
            )
        if resp.status_code in (401, 403):
            raise ProviderError(
                f"Aeroplan air-bounds returned {resp.status_code} — api_key may "
                "have rotated again; check docs/probes/v1c-aeroplan-endpoint-discovery.md."
            )
        if resp.status_code != 200:
            raise ProviderError(
                f"Aeroplan air-bounds failed: {resp.status_code} {resp.text[:200]}"
            )

        return _parse_air_bounds(resp.json(), origin, destination, depart_date, cabin)


def _parse_air_bounds(
    payload: dict[str, Any],
    origin: str,
    destination: str,
    depart_date: date,
    cabin: Cabin,
) -> list[AwardOffer]:
    """Parse Aeroplan air-bounds response into AwardOffers.

    Defensive parsing: Aeroplan's response shape is nested and undocumented;
    we extract what we need (points, taxes, operating carrier) and skip rows
    we can't parse rather than crashing the whole search."""
    offers: list[AwardOffer] = []
    target_cabin = _CABIN_MAP[cabin]

    for group in payload.get("data", {}).get("airBoundGroups", []):
        bound = group.get("boundDetails", {}) or group.get("airBound", {})
        segments = bound.get("segments", [])
        if not segments:
            continue
        carrier = (
            segments[0].get("flight", {}).get("marketingAirlineCode")
            or segments[0].get("marketingAirlineCode")
            or segments[0].get("operatingAirlineCode", "")
        )

        for fare in group.get("airBoundDetails", {}).get("fareFamilies", []) or group.get(
            "fareFamilies", []
        ):
            cabin_label = (fare.get("hierarchy") or fare.get("cabin") or "").lower()
            if target_cabin not in cabin_label:
                continue
            try:
                points = int(fare["pricing"]["points"])
                taxes = float(fare["pricing"].get("totalTaxes", 0))
                taxes_currency = fare["pricing"].get("currencyCode", "USD")
            except (KeyError, ValueError, TypeError):
                continue

            # Convert taxes to USD-cents conservatively; Aeroplan typically
            # returns CAD. For MVP we record the original currency and let
            # the CPP layer warn if it isn't USD.
            taxes_cents = int(round(taxes * 100))

            offers.append(
                AwardOffer(
                    provider="AC",
                    operating_carrier=carrier or "**",
                    origin=origin.upper(),
                    destination=destination.upper(),
                    depart_date=depart_date,
                    cabin=cabin,
                    points=points,
                    taxes_cents=taxes_cents,
                    taxes_currency=taxes_currency,
                    fare_class=fare.get("fareFamilyCode"),
                    stops=max(0, len(segments) - 1),
                )
            )

    return offers
