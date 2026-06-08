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

import json
import logging
import uuid
from datetime import date
from typing import Any

import httpx

from autopoints.providers.base import AwardProvider, ProviderError
from autopoints.search.models import AwardOffer, Cabin

logger = logging.getLogger(__name__)

# Updated 2026-06-08 per docs/probes/v1c-aeroplan-endpoint-discovery.md.
_HOST = "akamai-gw.dbaas.aircanada.com"
_AIR_BOUNDS_ENDPOINT = (
    f"https://{_HOST}/loyalty/dapidynamicplus/1ASIUDALAC/v2/search/air-bounds"
)
_MARKET_TOKEN_ENDPOINT = (
    f"https://{_HOST}/loyalty/dapidynamicplus/1ASIUDALAC/v2/reward/market-token"
)
_COGNITO_ENDPOINT = "https://cognito-identity.us-east-2.amazonaws.com/"

# Cognito unauthenticated identity pool used by aircanada.com's public web
# client (hardcoded in their main.js bundle). This is the STABLE identifier
# — fresh per-call IdentityIds are minted at runtime via GetId so we don't
# have to refresh anything when AC revokes a specific ID. See
# `docs/probes/v1c-aeroplan-identity-refresh.md` for the discovery story.
_COGNITO_IDENTITY_POOL_ID = "us-east-2:4a7f6b48-a8ab-499b-9e7f-31e79b54638e"

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
        """v1.c-2 Kasada-bypass path via Browserbase.

        Sequence (per docs/probes/v1c-aeroplan-endpoint-discovery.md §5):

        1. Open a Browserbase session via `_browserbase.get_session()`. The
           Browserbase residential proxy + stealth fingerprint clears the
           Kasada challenge naturally on page load.
        2. Navigate to a Kasada-protected aircanada.com page so the challenge
           script runs and sets the `x-kpsdk-cd` cookie scoped to the
           aircanada.com domain.
        3. Do Cognito identity exchange server-side via httpx (the Cognito
           endpoint is on `cognito-identity.us-east-2.amazonaws.com`, not
           Kasada-protected, so this works without the browser).
        4. Sign the market-token request server-side with SigV4 and fire it
           via `page.evaluate(fetch)` so the in-browser request carries the
           Kasada cookies. Same for air-bounds.
        5. Parse the air-bounds JSON with the existing `_parse_air_bounds`
           helper.
        """
        try:
            from autopoints.providers._browserbase import get_session
        except ImportError as e:
            raise ProviderError(
                f"Aeroplan via Browserbase: import failed: {e}"
            ) from e

        page, browser = await get_session()
        try:
            # Step 1+2: warm up Kasada cookies. The /aeroplan/use-points/
            # landing page is the natural target — it's the page the
            # Aeroplan booking widget loads from, so Kasada solves there
            # with cookies scoped for the akamai-gw.dbaas.aircanada.com
            # API host (Kasada cookies are typically wildcard *.aircanada.com).
            logger.info("Aeroplan: navigating to aircanada.com to warm Kasada")
            await page.goto(
                "https://www.aircanada.com/aeroplan/use-points/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            # Kasada's challenge JS executes after DOMContentLoaded. Give it
            # a few seconds. A more rigorous approach is to wait for the
            # x-kpsdk-cd cookie to appear; this timeout is a pragmatic floor.
            await page.wait_for_timeout(5_000)

            # Step 3: Cognito identity exchange (server-side, not Kasada-protected).
            creds = await self._get_cognito_credentials()

            # Step 4a: SigV4-sign + fire market-token from inside the page.
            signed = self._build_signed_market_token_request(creds)
            logger.info("Aeroplan: firing in-page market-token request")
            market_resp = await page.evaluate(
                """async (req) => {
                    const r = await fetch(req.url, {
                        method: 'POST',
                        headers: req.headers,
                        body: req.body,
                        credentials: 'include',
                    });
                    return { status: r.status, body: await r.text() };
                }""",
                signed,
            )
            if market_resp["status"] != 200:
                raise ProviderError(
                    f"Aeroplan via Browserbase: market-token returned "
                    f"{market_resp['status']}: {market_resp['body'][:300]}"
                )
            try:
                session_token = json.loads(market_resp["body"])["data"]["sessionToken"]
            except (KeyError, ValueError) as e:
                raise ProviderError(
                    f"Aeroplan via Browserbase: market-token shape unexpected: {e}"
                ) from e

            # Step 4b: fire air-bounds from inside the page.
            air_bounds_req = {
                "url": _AIR_BOUNDS_ENDPOINT,
                "headers": {
                    "Content-Type": "application/json",
                    "x-api-key": self._api_key,
                    "ama-client-ref": str(uuid.uuid4()),
                    "ama-session-token": session_token,
                },
                "body": json.dumps(body),
            }
            logger.info("Aeroplan: firing in-page air-bounds request")
            air_resp = await page.evaluate(
                """async (req) => {
                    const r = await fetch(req.url, {
                        method: 'POST',
                        headers: req.headers,
                        body: req.body,
                        credentials: 'include',
                    });
                    return { status: r.status, body: await r.text() };
                }""",
                air_bounds_req,
            )
            if air_resp["status"] != 200:
                raise ProviderError(
                    f"Aeroplan via Browserbase: air-bounds returned "
                    f"{air_resp['status']}: {air_resp['body'][:300]}"
                )

            # Step 5: parse with the existing helper.
            return _parse_air_bounds(
                json.loads(air_resp["body"]), origin, destination, depart_date, cabin
            )
        finally:
            # Always close the browser to release the Browserbase session
            # (Browserbase bills by session-minutes; leaked sessions cost real money).
            await browser.close()

    async def _get_cognito_identity_id(self) -> str:
        """Mint a fresh unauthenticated IdentityId from the pool.

        The pool itself is the stable identifier (hardcoded in aircanada.com's
        main.js). Each call to GetId returns an ephemeral IdentityId that's
        valid until AC revokes it — by always minting fresh we avoid the
        problem of a revoked hardcoded value breaking us in production.
        Cheap call (one POST, returns one short string), so we do it on
        every search rather than caching.
        """
        try:
            resp = await self._client.post(
                _COGNITO_ENDPOINT,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "AWSCognitoIdentityService.GetId",
                },
                json={"IdentityPoolId": _COGNITO_IDENTITY_POOL_ID},
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"Aeroplan: Cognito GetId failed: {e}") from e
        if resp.status_code != 200:
            raise ProviderError(
                f"Aeroplan: Cognito GetId returned {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()["IdentityId"]
        except (KeyError, ValueError) as e:
            raise ProviderError(
                f"Aeroplan: Cognito GetId response missing IdentityId: {e}"
            ) from e

    async def _get_cognito_credentials(self) -> dict[str, str]:
        """Mint a fresh IdentityId then exchange it for ephemeral AWS creds.

        Two-step Cognito flow:
        1. GetId(pool_id) → IdentityId (ephemeral, anonymous, freshly minted)
        2. GetCredentialsForIdentity(IdentityId) → {AccessKeyId, SecretKey, SessionToken}

        Returns the credentials dict with AccessKeyId/SecretKey/SessionToken.
        """
        identity_id = await self._get_cognito_identity_id()
        try:
            resp = await self._client.post(
                _COGNITO_ENDPOINT,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "AWSCognitoIdentityService.GetCredentialsForIdentity",
                },
                json={"IdentityId": identity_id},
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"Aeroplan: Cognito GetCredentialsForIdentity failed: {e}") from e
        if resp.status_code != 200:
            raise ProviderError(
                f"Aeroplan: Cognito GetCredentialsForIdentity returned "
                f"{resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()["Credentials"]
        except (KeyError, ValueError) as e:
            raise ProviderError(
                f"Aeroplan: Cognito response missing Credentials: {e}"
            ) from e

    def _build_signed_market_token_request(
        self, creds: dict[str, str]
    ) -> dict[str, Any]:
        """Build the SigV4-signed market-token request as a serializable dict.

        Returns ``{"url": str, "headers": dict, "body": str}`` suitable for
        either an httpx call (direct path) or a page.evaluate fetch (v1.c-2
        Browserbase path). Extracted so both paths share signing.
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
        return {
            "url": _MARKET_TOKEN_ENDPOINT,
            "headers": dict(aws_req.headers.items()),
            "body": market_body.decode("utf-8"),
        }

    async def _get_market_token(self, creds: dict[str, str]) -> str:
        """Step 2: SigV4-sign a POST to the market-token endpoint; return
        the sessionToken needed by air-bounds.
        """
        signed = self._build_signed_market_token_request(creds)
        try:
            resp = await self._client.post(
                signed["url"],
                headers=signed["headers"],
                content=signed["body"].encode("utf-8"),
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
