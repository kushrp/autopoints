from __future__ import annotations

import time
from datetime import date
from typing import Any

import httpx

from autopoints.providers.base import CashProvider, ProviderError
from autopoints.search.models import Cabin, FlightOffer

_CABIN_MAP = {
    Cabin.economy: "ECONOMY",
    Cabin.premium_economy: "PREMIUM_ECONOMY",
    Cabin.business: "BUSINESS",
    Cabin.first: "FIRST",
}


class AmadeusProvider(CashProvider):
    name = "amadeus"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        hostname: str = "test",
        client: httpx.AsyncClient | None = None,
    ):
        if not client_id or not client_secret:
            raise ProviderError(
                "Amadeus credentials missing. Set AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._base = (
            "https://test.api.amadeus.com" if hostname == "test"
            else "https://api.amadeus.com"
        )
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        resp = await self._client.post(
            f"{self._base}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise ProviderError(f"Amadeus auth failed: {resp.status_code} {resp.text}")
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + float(body.get("expires_in", 1799))
        return self._token

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[FlightOffer]:
        token = await self._get_token()
        params = {
            "originLocationCode": origin.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": depart_date.isoformat(),
            "adults": str(passengers),
            "travelClass": _CABIN_MAP[cabin],
            "currencyCode": "USD",
            "max": "20",
            "nonStop": "false",
        }
        resp = await self._client.get(
            f"{self._base}/v2/shopping/flight-offers",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        if resp.status_code != 200:
            raise ProviderError(
                f"Amadeus search failed: {resp.status_code} {resp.text[:200]}"
            )
        return _parse_offers(resp.json(), origin, destination, depart_date, cabin)


def _parse_offers(
    payload: dict[str, Any],
    origin: str,
    destination: str,
    depart_date: date,
    cabin: Cabin,
) -> list[FlightOffer]:
    offers: list[FlightOffer] = []
    for raw in payload.get("data", []):
        try:
            price = raw["price"]["grandTotal"]
            currency = raw["price"].get("currency", "USD")
            cents = int(round(float(price) * 100))
            itineraries = raw.get("itineraries", [])
            if not itineraries:
                continue
            segments = itineraries[0].get("segments", [])
            if not segments:
                continue
            carrier = segments[0].get("carrierCode", "")
            flight_numbers = [
                f"{s.get('carrierCode', '')}{s.get('number', '')}" for s in segments
            ]
            duration_min = _parse_iso_duration(itineraries[0].get("duration", "PT0M"))
            offers.append(
                FlightOffer(
                    provider="amadeus",
                    origin=origin.upper(),
                    destination=destination.upper(),
                    depart_date=depart_date,
                    cabin=cabin,
                    carrier=carrier,
                    flight_numbers=flight_numbers,
                    cash_cents=cents,
                    currency=currency,
                    duration_minutes=duration_min,
                    stops=max(0, len(segments) - 1),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return offers


def _parse_iso_duration(s: str) -> int:
    """Parse ISO-8601 duration like 'PT5H30M' to minutes."""
    if not s.startswith("PT"):
        return 0
    s = s[2:]
    hours = 0
    minutes = 0
    if "H" in s:
        h_str, _, s = s.partition("H")
        hours = int(h_str)
    if "M" in s:
        m_str, _, _ = s.partition("M")
        minutes = int(m_str)
    return hours * 60 + minutes
