from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from autopoints.providers.base import AwardProvider, ProviderError
from autopoints.search.models import AwardOffer, Cabin

# Aeroplan's public award-search endpoint, used by the aircanada.com booking
# widget. This is a reverse-engineered public endpoint, not an official API —
# request/response schema can change without notice. The static-chart provider
# is the safety net.
_ENDPOINT = (
    "https://akamai-akwa-aeroplan.aircanada.com"
    "/loyalty/dapidynamic/1ASIUDALAC/v2/search/air-bounds"
)
_DEFAULT_API_KEY = "1ASIUDALAC"  # public widget key, observable in browser devtools

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
    ):
        self._api_key = api_key
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
        body = {
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
        }
        try:
            resp = await self._client.post(
                _ENDPOINT,
                headers={"x-api-key": self._api_key},
                json=body,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"Aeroplan request failed: {e}") from e

        if resp.status_code in (401, 403):
            raise ProviderError(
                f"Aeroplan returned {resp.status_code} — likely bot-blocked or "
                "the public api_key has rotated. Inspect the live aircanada.com "
                "award search in browser devtools and update _DEFAULT_API_KEY."
            )
        if resp.status_code != 200:
            raise ProviderError(
                f"Aeroplan search failed: {resp.status_code} {resp.text[:200]}"
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

        for fare in group.get("airBoundDetails", {}).get("fareFamilies", []) or group.get("fareFamilies", []):
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
