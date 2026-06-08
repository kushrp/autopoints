from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from autopoints.cache.store import TTLCache
from autopoints.pricing.cpp import build_redemption
from autopoints.programs.loader import valuations
from autopoints.providers.base import AwardProvider, CashProvider
from autopoints.search.models import (
    AwardOffer,
    Cabin,
    FlightOffer,
    RedemptionResult,
    SearchRequest,
)

# Short timezone aliases accepted by the --arrive-before filter. Maps to IANA
# zone names. Extend by adding entries — order matches the US-time-zone
# observations most travelers reason in.
_TZ_ALIASES: dict[str, str] = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
    "AKT": "America/Anchorage",
    "HT": "Pacific/Honolulu",
}

_ARRIVE_BEFORE_RE = re.compile(r"^(\d{1,2}):(\d{2})([A-Z]+)$")


class ArriveBeforeParseError(ValueError):
    """Raised when --arrive-before doesn't match the expected HH:MM<TZ> shape."""

CASH_TTL = 60 * 60  # 1 hour
AWARD_TTL = 6 * 60 * 60  # 6 hours


@dataclass
class SearchOutcome:
    request: SearchRequest
    cash_offers: list[FlightOffer] = field(default_factory=list)
    award_offers: list[AwardOffer] = field(default_factory=list)
    redemptions: list[RedemptionResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def best_per_program(self) -> list[RedemptionResult]:
        best: dict[tuple[str, str], RedemptionResult] = {}
        for r in self.redemptions:
            key = (r.transfer_program, r.points_program)
            current = best.get(key)
            if current is None or r.effective_cpp > current.effective_cpp:
                best[key] = r
        return sorted(best.values(), key=lambda r: r.effective_cpp, reverse=True)


class Orchestrator:
    def __init__(
        self,
        cash_providers: list[CashProvider],
        award_providers: list[AwardProvider],
        cache: TTLCache,
        cpp_great: float = 2.0,
        cpp_good: float = 1.5,
        force_refresh: bool = False,
    ):
        self.cash_providers = cash_providers
        self.award_providers = award_providers
        self.cache = cache
        self.cpp_great = cpp_great
        self.cpp_good = cpp_good
        self.force_refresh = force_refresh

    async def run(
        self,
        request: SearchRequest,
        transfer_currencies: list[str] | None = None,
    ) -> SearchOutcome:
        currencies = transfer_currencies or ["UR", "MR", "DIRECT"]
        outcome = SearchOutcome(request=request)
        dates = request.date_window()

        cash_tasks = [
            self._cash_with_cache(p, request.origin, request.destination, d, request.cabin, request.passengers)
            for p in self.cash_providers
            for d in dates
        ]
        award_tasks = [
            self._award_with_cache(p, request.origin, request.destination, d, request.cabin, request.passengers)
            for p in self.award_providers
            for d in dates
        ]

        cash_results, award_results = await asyncio.gather(
            asyncio.gather(*cash_tasks, return_exceptions=True),
            asyncio.gather(*award_tasks, return_exceptions=True),
        )

        for r in cash_results:
            if isinstance(r, Exception):
                outcome.warnings.append(f"cash provider failed: {r}")
            else:
                outcome.cash_offers.extend(r)
        for r in award_results:
            if isinstance(r, Exception):
                outcome.warnings.append(f"award provider failed: {r}")
            else:
                outcome.award_offers.extend(r)

        # For each award offer, find the cheapest matching cash offer (same date)
        # and build redemptions for each transfer currency.
        vals = valuations()
        for award in outcome.award_offers:
            cash = _cheapest_cash_for(outcome.cash_offers, award.depart_date)
            if cash is None:
                continue
            for currency in currencies:
                redemption = build_redemption(
                    cash=cash,
                    award=award,
                    from_currency=currency,  # type: ignore[arg-type]
                    valuations=vals,
                    cpp_great=self.cpp_great,
                    cpp_good=self.cpp_good,
                )
                if redemption is not None:
                    outcome.redemptions.append(redemption)

        # Post-rank arrival-time filter. Chart-floor results (no time fields)
        # are kept — the user sees them with their lower-confidence framing
        # rather than silently losing them when a filter is in play.
        if request.arrive_before_local:
            try:
                outcome.redemptions = _filter_arrive_before(
                    outcome.redemptions, request.arrive_before_local
                )
            except ArriveBeforeParseError as e:
                outcome.warnings.append(str(e))

        return outcome

    async def _cash_with_cache(
        self,
        provider: CashProvider,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int,
    ) -> list[FlightOffer]:
        key = f"cash:{provider.name}:{origin}:{destination}:{depart_date.isoformat()}:{cabin.value}:{passengers}"
        if not self.force_refresh:
            hit = self.cache.get(key)
            if hit is not None:
                raw, _ = hit
                return [FlightOffer(**o) for o in raw]
        offers = await provider.search(origin, destination, depart_date, cabin, passengers)
        self.cache.set(key, [json.loads(o.model_dump_json()) for o in offers], CASH_TTL)
        return offers

    async def _award_with_cache(
        self,
        provider: AwardProvider,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int,
    ) -> list[AwardOffer]:
        key = f"award:{provider.name}:{provider.program_code}:{origin}:{destination}:{depart_date.isoformat()}:{cabin.value}:{passengers}"
        if not self.force_refresh:
            hit = self.cache.get(key)
            if hit is not None:
                raw, _ = hit
                return [AwardOffer(**o) for o in raw]
        offers = await provider.search(origin, destination, depart_date, cabin, passengers)
        self.cache.set(key, [json.loads(o.model_dump_json()) for o in offers], AWARD_TTL)
        return offers


def _cheapest_cash_for(offers: list[FlightOffer], on_date: date) -> FlightOffer | None:
    matching = [o for o in offers if o.depart_date == on_date]
    if not matching:
        return None
    return min(matching, key=lambda o: o.cash_cents)


def parse_arrive_before(spec: str) -> tuple[time, ZoneInfo]:
    """Parse `HH:MM<TZ>` into `(time, ZoneInfo)`.

    Examples: `08:00ET`, `14:30PT`, `06:00MT`.
    Raises ArriveBeforeParseError for malformed input or unknown TZ aliases.
    """
    match = _ARRIVE_BEFORE_RE.match(spec.strip().upper())
    if not match:
        raise ArriveBeforeParseError(
            f"--arrive-before must look like 'HH:MM<TZ>' (e.g. '08:00ET'); got {spec!r}"
        )
    hh, mm, tz_alias = match.groups()
    try:
        wall = time(int(hh), int(mm))
    except ValueError as e:
        raise ArriveBeforeParseError(
            f"--arrive-before time-of-day invalid: {spec!r} ({e})"
        ) from e
    iana = _TZ_ALIASES.get(tz_alias)
    if iana is None:
        known = ", ".join(sorted(_TZ_ALIASES))
        raise ArriveBeforeParseError(
            f"--arrive-before TZ {tz_alias!r} not recognized; expected one of: {known}"
        )
    return wall, ZoneInfo(iana)


def _offer_arrival_dt(
    offer: FlightOffer | AwardOffer, filter_tz: ZoneInfo
) -> datetime | None:
    """Resolve an offer's arrival to an absolute datetime in its own dest_tz.

    Returns None when the offer carries no time-of-day fields (chart-floor
    case). Falls back to `filter_tz` when `offer.dest_tz` is absent, which
    preserves back-compat for fixtures that don't populate dest_tz.
    """
    if offer.arrival_time is None or offer.arrival_date is None:
        return None
    offer_tz = ZoneInfo(offer.dest_tz) if offer.dest_tz else filter_tz
    return datetime.combine(offer.arrival_date, offer.arrival_time, tzinfo=offer_tz)


def _filter_arrive_before(
    redemptions: list[RedemptionResult], spec: str
) -> list[RedemptionResult]:
    """Drop redemptions whose arrival is at or after the filter cutoff.

    The cutoff is anchored to the calendar day the offer's arrival lands on
    when viewed in the filter's TZ — so a Tokyo redeye arriving 08:30 JST on
    Oct 16 (= 19:30 ET on Oct 15) is compared against 08:00 ET on Oct 15,
    not against 08:00 ET on Oct 16. This is the correct semantic for "the
    flight arrived before {wall} {filter_tz}-time on the day it actually
    landed in {filter_tz}." Chart-floor offers (no time fields) pass the
    filter — the user sees them with their existing 'chart-floor only'
    framing rather than losing them silently.
    """
    wall, filter_tz = parse_arrive_before(spec)
    out: list[RedemptionResult] = []
    for r in redemptions:
        arr_dt = _offer_arrival_dt(r.award_offer, filter_tz)
        if arr_dt is None:
            # Chart-floor or otherwise time-less — keep.
            out.append(r)
            continue
        filter_day = arr_dt.astimezone(filter_tz).date()
        cutoff_dt = datetime.combine(filter_day, wall, tzinfo=filter_tz)
        if arr_dt < cutoff_dt:
            out.append(r)
    return out
