"""Demo providers: deterministic synthetic data so the app works end-to-end
without API credentials. Useful for first-run demos, tests, and offline dev."""

from __future__ import annotations

from datetime import date

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

        return [
            FlightOffer(
                provider="demo",
                origin=origin.upper(),
                destination=destination.upper(),
                depart_date=depart_date,
                cabin=cabin,
                carrier="UA",
                flight_numbers=["UA1"],
                cash_cents=base * passengers,
                duration_minutes=int(distance / 7),
                stops=0,
            ),
            FlightOffer(
                provider="demo",
                origin=origin.upper(),
                destination=destination.upper(),
                depart_date=depart_date,
                cabin=cabin,
                carrier="AA",
                flight_numbers=["AA10", "AA20"],
                cash_cents=int(base * 0.85) * passengers,  # cheaper 1-stop
                duration_minutes=int(distance / 6),
                stops=1,
            ),
            FlightOffer(
                provider="demo",
                origin=origin.upper(),
                destination=destination.upper(),
                depart_date=depart_date,
                cabin=cabin,
                carrier="DL",
                flight_numbers=["DL5"],
                cash_cents=int(base * 1.15) * passengers,  # premium nonstop
                duration_minutes=int(distance / 7),
                stops=0,
            ),
        ]
