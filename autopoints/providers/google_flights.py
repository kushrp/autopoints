"""Google Flights cash provider via the `fli` library.

Replaces the Amadeus self-service provider (decommissioned 2026-07-17).
`fli` is the Python library at https://github.com/punitarani/fli — it hits
Google's `tfs=` protobuf backend through `curl_cffi` (TLS-fingerprint
impersonation), no browser session required.

Trade-off: the protobuf schema is undocumented and has historically drifted
without notice. When `fli` breaks, this provider raises `ProviderError` and
the orchestrator surfaces it as a warning — the user keeps getting chart-floor
award results until upstream patches. A Browserbase + Playwright fallback
adapter is the phase-2 mitigation.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING, Any

from autopoints.providers.base import CashProvider, ProviderError
from autopoints.search.models import Cabin, FlightOffer

if TYPE_CHECKING:
    from fli.models import FlightResult

_SEAT_TYPE_MAP_NAMES = {
    Cabin.economy: "ECONOMY",
    Cabin.premium_economy: "PREMIUM_ECONOMY",
    Cabin.business: "BUSINESS",
    Cabin.first: "FIRST",
}


class GoogleFlightsProvider(CashProvider):
    name = "google_flights"

    def __init__(self, top_n: int = 20):
        self._top_n = top_n

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[FlightOffer]:
        try:
            results = await asyncio.to_thread(
                _search_sync, origin, destination, depart_date, cabin, passengers, self._top_n
            )
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 — fli wraps several network/parse exceptions
            raise ProviderError(f"google_flights: fli search failed: {e}") from e

        if results is None:
            return []
        offers: list[FlightOffer] = []
        for r in results:
            # One-way returns FlightResult; round-trip returns tuples — we only
            # do one-way at this layer.
            if isinstance(r, tuple):
                continue
            offer = _to_flight_offer(r, origin, destination, depart_date, cabin)
            if offer is not None:
                offers.append(offer)
        return offers


def _search_sync(
    origin: str,
    destination: str,
    depart_date: date,
    cabin: Cabin,
    passengers: int,
    top_n: int,
) -> list[Any] | None:
    """Synchronous wrapper. Lives at module scope so it can be patched in tests."""
    # Imports are inside the function so the module imports cleanly even when
    # `flights` (the fli package) is not installed — the provider will raise
    # ProviderError at runtime instead.
    try:
        from fli.models import (
            Airport,
            FlightSearchFilters,
            FlightSegment,
            MaxStops,
            PassengerInfo,
            SeatType,
            TripType,
        )
        from fli.search import SearchFlights
    except ImportError as e:
        raise ProviderError(
            "google_flights: `flights` package not installed. "
            "Run `pip install git+https://github.com/punitarani/fli.git`."
        ) from e

    try:
        seat_type = SeatType[_SEAT_TYPE_MAP_NAMES[cabin]]
        dep_airport = Airport[origin.upper()]
        arr_airport = Airport[destination.upper()]
    except KeyError as e:
        raise ProviderError(f"google_flights: unsupported airport or cabin: {e}") from e

    filters = FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=passengers),
        flight_segments=[
            FlightSegment(
                departure_airport=[[dep_airport, 0]],
                arrival_airport=[[arr_airport, 0]],
                travel_date=depart_date.isoformat(),
            )
        ],
        seat_type=seat_type,
        stops=MaxStops.ANY,
    )
    return SearchFlights().search(filters, top_n=top_n)


def _to_flight_offer(
    result: "FlightResult",
    origin: str,
    destination: str,
    depart_date: date,
    cabin: Cabin,
) -> FlightOffer | None:
    """Map a single `fli.FlightResult` to a `FlightOffer`. Returns None for
    unparseable rows (missing legs, malformed price, etc.) so the caller can
    keep collecting partial results."""
    try:
        legs = getattr(result, "legs", None) or []
        if not legs:
            return None
        first = legs[0]
        last = legs[-1]
        carrier = _airline_code(first.airline)
        flight_numbers = [f"{_airline_code(leg.airline)}{leg.flight_number}" for leg in legs]
        cash_cents = int(round(float(result.price) * 100))
        dep_dt = first.departure_datetime
        arr_dt = last.arrival_datetime
    except (AttributeError, TypeError, ValueError):
        return None

    return FlightOffer(
        provider="google_flights",
        origin=origin.upper(),
        destination=destination.upper(),
        depart_date=depart_date,
        cabin=cabin,
        carrier=carrier,
        flight_numbers=flight_numbers,
        cash_cents=cash_cents,
        currency="USD",
        duration_minutes=getattr(result, "duration", None),
        stops=getattr(result, "stops", 0),
        departure_time=dep_dt.time() if dep_dt else None,
        arrival_time=arr_dt.time() if arr_dt else None,
        arrival_date=arr_dt.date() if arr_dt else None,
    )


def _airline_code(airline: Any) -> str:
    """Extract the IATA code from a fli `Airline` enum value."""
    # `Airline` is a StrEnum-like; `.name` is the IATA code (e.g. "AA", "B6").
    return getattr(airline, "name", str(airline))
