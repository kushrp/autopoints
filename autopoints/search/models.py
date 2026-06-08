from __future__ import annotations

from datetime import date, time
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Cabin(StrEnum):
    economy = "economy"
    premium_economy = "premium_economy"
    business = "business"
    first = "first"


class SearchRequest(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_date: date
    window_days: int = 0
    cabin: Cabin = Cabin.economy
    passengers: int = 1
    arrive_before_local: str | None = None
    """Filter format `HH:MM<TZ>` where TZ ∈ {ET,CT,MT,PT}, e.g. `08:00ET`.
    Applied post-rank by the orchestrator against `arrival_time` + `arrival_date`
    in `dest_tz`. Offers with no time fields (chart-floor results) pass."""

    def date_window(self) -> list[date]:
        from datetime import timedelta

        return [
            self.depart_date + timedelta(days=d)
            for d in range(-self.window_days, self.window_days + 1)
        ]


class FlightOffer(BaseModel):
    provider: str
    origin: str
    destination: str
    depart_date: date
    cabin: Cabin
    carrier: str
    flight_numbers: list[str] = []
    cash_cents: int
    currency: str = "USD"
    duration_minutes: int | None = None
    stops: int = 0
    # Time-of-day fields are optional so chart-floor providers and pre-migration
    # cached blobs remain valid. `arrival_date` carries the next-day case for
    # redeyes that cross midnight.
    departure_time: time | None = None
    arrival_time: time | None = None
    arrival_date: date | None = None
    origin_tz: str | None = None  # IANA name, e.g. "America/Los_Angeles"
    dest_tz: str | None = None


class AwardOffer(BaseModel):
    provider: str  # the loyalty program issuing the award (e.g. "AC" for Aeroplan)
    operating_carrier: str  # the airline actually flying the metal (e.g. "UA")
    origin: str
    destination: str
    depart_date: date
    cabin: Cabin
    points: int
    taxes_cents: int
    taxes_currency: str = "USD"
    fare_class: str | None = None
    stops: int = 0
    departure_time: time | None = None
    arrival_time: time | None = None
    arrival_date: date | None = None
    origin_tz: str | None = None
    dest_tz: str | None = None


class RedemptionResult(BaseModel):
    """One row of the final ranked output: redeem `points_program` points
    (sourced from `transfer_program` if a transfer is required) for the
    `award_offer`, valued against the cheapest matching `cash_offer`."""

    transfer_program: Literal["UR", "MR", "DIRECT"]
    points_program: str  # e.g. "AC"
    points_required: int  # after applying transfer ratio
    effective_points_required: int  # after applying any active transfer bonus
    cash_offer: FlightOffer
    award_offer: AwardOffer
    cpp: float  # nominal cents per point
    effective_cpp: float  # after transfer bonus
    valuation_cpp: float  # the program's reference cents/point
    verdict: Literal["great", "good", "ok", "bad"]
    notes: list[str] = []
