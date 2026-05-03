from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from autopoints.cache.store import TTLCache
from autopoints.providers.base import AwardProvider, CashProvider, ProviderError
from autopoints.search.models import AwardOffer, Cabin, FlightOffer, SearchRequest
from autopoints.search.orchestrator import Orchestrator


class _StubCash(CashProvider):
    name = "stub_cash"

    def __init__(self, cents: int = 18000):
        self.cents = cents
        self.calls = 0

    async def search(self, origin, destination, depart_date, cabin, passengers=1):
        self.calls += 1
        return [
            FlightOffer(
                provider=self.name,
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                cabin=cabin,
                carrier="UA",
                flight_numbers=["UA100"],
                cash_cents=self.cents,
            )
        ]


class _StubAward(AwardProvider):
    name = "stub_award"
    program_code = "AC"

    def __init__(self, points: int = 12500):
        self.points = points
        self.calls = 0

    async def search(self, origin, destination, depart_date, cabin, passengers=1):
        self.calls += 1
        return [
            AwardOffer(
                provider=self.program_code,
                operating_carrier="UA",
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                cabin=cabin,
                points=self.points,
                taxes_cents=560,
            )
        ]


class _FailingAward(AwardProvider):
    name = "failing_award"
    program_code = "BA"

    async def search(self, *args, **kwargs):
        raise ProviderError("simulated failure")


@pytest.fixture()
def cache(tmp_path: Path) -> TTLCache:
    return TTLCache(tmp_path / "cache.db")


async def test_orchestrator_basic_flow(cache: TTLCache):
    cash = _StubCash(cents=30000)  # high cash -> good CPP
    award = _StubAward()
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert len(out.cash_offers) == 1
    assert len(out.award_offers) == 1
    assert len(out.redemptions) == 1
    r = out.redemptions[0]
    assert r.transfer_program == "UR"
    assert r.points_program == "AC"
    assert r.verdict in ("good", "great")


async def test_orchestrator_caches_provider_calls(cache: TTLCache):
    cash = _StubCash()
    award = _StubAward()
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
    )
    await orch.run(req)
    await orch.run(req)
    assert cash.calls == 1
    assert award.calls == 1


async def test_orchestrator_force_refresh_bypasses_cache(cache: TTLCache):
    cash = _StubCash()
    award = _StubAward()
    orch = Orchestrator([cash], [award], cache, force_refresh=True)
    req = SearchRequest(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
    )
    await orch.run(req)
    await orch.run(req)
    assert cash.calls == 2
    assert award.calls == 2


async def test_orchestrator_award_failure_does_not_kill_search(cache: TTLCache):
    cash = _StubCash()
    failing = _FailingAward()
    orch = Orchestrator([cash], [failing], cache)
    req = SearchRequest(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
    )
    out = await orch.run(req)
    assert len(out.cash_offers) == 1
    assert len(out.award_offers) == 0
    assert len(out.warnings) == 1
    assert "simulated failure" in out.warnings[0]


async def test_orchestrator_date_window_expands_searches(cache: TTLCache):
    cash = _StubCash()
    award = _StubAward()
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=2, cabin=Cabin.economy,
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    # 5 dates (-2..+2) * 1 provider each
    assert cash.calls == 5
    assert award.calls == 5
    assert len(out.cash_offers) == 5
    assert len(out.award_offers) == 5
    # best_per_program collapses to one row per (transfer, program) pair
    assert len(out.best_per_program()) == 1
