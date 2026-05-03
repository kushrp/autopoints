from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date

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
