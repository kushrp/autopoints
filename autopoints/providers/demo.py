"""Demo providers: deterministic synthetic data so the app works end-to-end
without API credentials. Useful for first-run demos, tests, and offline dev."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from autopoints.programs.geo import haversine_miles
from autopoints.providers.base import CashProvider
from autopoints.search.models import Cabin, FlightOffer

# Rough per-mile cash rates by cabin (USD cents per statute mile).
# Calibrated against typical 2026 US domestic fares as a sanity-grade approximation.
_CABIN_CENTS_PER_MILE = {
    Cabin.economy: 12,
    Cabin.premium_economy: 22,
    Cabin.business: 55,
    Cabin.first: 90,
}
_BASE_FARE_CENTS = {
    Cabin.economy: 6000,
    Cabin.premium_economy: 12000,
    Cabin.business: 25000,
    Cabin.first: 40000,
}


class DemoCashProvider(CashProvider):
    """Synthetic cash flights based on great-circle distance × per-mile rate.

    Generates three offers per call (cheapest nonstop, mid-tier 1-stop, premium
    nonstop) so the orchestrator's "cheapest match" logic has something to do."""

    name = "demo"

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[FlightOffer]:
        try:
            distance = haversine_miles(origin, destination)
        except KeyError:
            return []

        base = _BASE_FARE_CENTS[cabin] + int(distance * _CABIN_CENTS_PER_MILE[cabin])
        # Modulate by date so a window shows price variation
        day_jitter = (depart_date.toordinal() % 7) * 1000  # 0..6000c
        base += day_jitter

        # Three offer archetypes per route per date so the --arrive-before
        # filter has something to discriminate against in demo mode:
        # - "redeye"      : depart 22:00, lands early next morning
        # - "morning"     : depart 08:00, lands mid-day same day
        # - "afternoon"   : depart 14:00, lands evening same day
        # Times fall back to the filter's TZ in `_filter_arrive_before` when
        # `dest_tz` is None, which keeps demo data interpretable without
        # a real timezone lookup.
        nonstop_minutes = int(distance / 7)
        onestop_minutes = int(distance / 6)
        return [
            _build_offer(
                origin, destination, depart_date, cabin, "UA", ["UA1"],
                base * passengers, nonstop_minutes, 0,
                depart_hour=22,
            ),
            _build_offer(
                origin, destination, depart_date, cabin, "AA", ["AA10", "AA20"],
                int(base * 0.85) * passengers, onestop_minutes, 1,
                depart_hour=8,
            ),
            _build_offer(
                origin, destination, depart_date, cabin, "DL", ["DL5"],
                int(base * 1.15) * passengers, nonstop_minutes, 0,
                depart_hour=14,
            ),
        ]


def _build_offer(
    origin: str,
    destination: str,
    depart_date: date,
    cabin: Cabin,
    carrier: str,
    flight_numbers: list[str],
    cash_cents: int,
    duration_minutes: int,
    stops: int,
    depart_hour: int,
) -> FlightOffer:
    departure_dt = datetime.combine(depart_date, time(depart_hour, 0))
    arrival_dt = departure_dt + timedelta(minutes=duration_minutes)
    return FlightOffer(
        provider="demo",
        origin=origin.upper(),
        destination=destination.upper(),
        depart_date=depart_date,
        cabin=cabin,
        carrier=carrier,
        flight_numbers=flight_numbers,
        cash_cents=cash_cents,
        duration_minutes=duration_minutes,
        stops=stops,
        departure_time=departure_dt.time(),
        arrival_time=arrival_dt.time(),
        arrival_date=arrival_dt.date(),
    )
