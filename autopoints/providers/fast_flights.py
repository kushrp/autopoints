"""Google Flights cash provider via the `fast-flights` library.

A more resilient alternative to the `fli`-backed provider: `fast-flights`
(https://github.com/AWeirdDev/fast-flights) parses Google Flights' protobuf
response and survived schema drift that left `fli` returning None as of
June 2026. No API key, no browser session. Same upstream-fragility caveat as
any Google Flights scraper: on a parse break it raises ProviderError and the
orchestrator degrades to chart-floor.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from datetime import date
from typing import Any, Literal

from autopoints.providers.base import CashProvider, ProviderError
from autopoints.search.models import Cabin, FlightOffer

logger = logging.getLogger(__name__)

_SeatLiteral = Literal["economy", "premium-economy", "business", "first"]

_SEAT_MAP: dict[Cabin, _SeatLiteral] = {
    Cabin.economy: "economy",
    Cabin.premium_economy: "premium-economy",
    Cabin.business: "business",
    Cabin.first: "first",
}


class FastFlightsProvider(CashProvider):
    name = "fast_flights"

    def __init__(self, top_n: int = 20, retries: int = 1) -> None:
        self._top_n = top_n
        self._retries = retries

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[FlightOffer]:
        for attempt in range(self._retries + 1):
            try:
                rows = await asyncio.to_thread(
                    _search_sync, origin, destination, depart_date, cabin, passengers
                )
                break
            except ProviderError:
                if attempt < self._retries:
                    logger.warning("fast-flights failed (attempt %d), retrying", attempt + 1)
                    continue
                raise
        offers = [
            offer
            for row in rows[: self._top_n]
            if (offer := _to_flight_offer(row, origin, destination, depart_date, cabin))
        ]
        return offers


def _search_sync(
    origin: str, destination: str, depart_date: date, cabin: Cabin, passengers: int
) -> list[Any]:
    try:
        from fast_flights import FlightQuery, Passengers, create_query, get_flights
    except ImportError as e:
        raise ProviderError(
            "fast_flights: package not installed. Run `uv pip install fast-flights`."
        ) from e

    query = create_query(
        flights=[
            FlightQuery(
                date=depart_date.isoformat(),
                from_airport=origin.upper(),
                to_airport=destination.upper(),
            )
        ],
        seat=_SEAT_MAP[cabin],
        trip="one-way",
        passengers=Passengers(adults=passengers),
        currency="USD",
    )
    try:
        result = get_flights(query)
    except Exception as e:  # noqa: BLE001 — fast-flights wraps network/parse errors
        raise ProviderError(f"fast_flights: search failed: {e}") from e
    return list(result)


def _to_flight_offer(
    row: Any, origin: str, destination: str, depart_date: date, cabin: Cabin
) -> FlightOffer | None:
    try:
        price = getattr(row, "price", None)
        legs = getattr(row, "flights", None) or []
        if price is None or not isinstance(price, (int, float)) or not legs:
            return None
        first, last = legs[0], legs[-1]
        carrier = getattr(row, "type", None) or (getattr(row, "airlines", None) or [""])[0]
        dep = _to_datetime(first.departure)
        arr = _to_datetime(last.arrival)
        duration = int((arr - dep).total_seconds() // 60) if dep and arr else None
    except (AttributeError, TypeError, ValueError, IndexError):
        return None

    return FlightOffer(
        provider="fast_flights",
        origin=origin.upper(),
        destination=destination.upper(),
        depart_date=depart_date,
        cabin=cabin,
        carrier=str(carrier),
        flight_numbers=[],
        cash_cents=int(round(float(price) * 100)),
        currency="USD",
        duration_minutes=duration,
        stops=max(0, len(legs) - 1),
        departure_time=dep.time() if dep else None,
        arrival_time=arr.time() if arr else None,
        arrival_date=arr.date() if arr else None,
    )


def _to_datetime(simple: Any) -> dt.datetime | None:
    """fast-flights returns SimpleDatetime(date=[y,m,d], time=[h,m])."""
    d = getattr(simple, "date", None)
    t = getattr(simple, "time", None)
    if not d or not t:
        return None
    return dt.datetime(d[0], d[1], d[2], t[0], t[1])
