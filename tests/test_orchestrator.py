from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from autopoints.cache.store import TTLCache
from autopoints.providers.base import AwardProvider, CashProvider, ProviderError
from autopoints.search.models import AwardOffer, Cabin, FlightOffer, SearchRequest
from autopoints.search.orchestrator import (
    ArriveBeforeParseError,
    Orchestrator,
    parse_arrive_before,
)


class _StubCash(CashProvider):
    name = "stub_cash"

    def __init__(
        self,
        cents: int = 18000,
        arrival_time: time | None = None,
        arrival_date: date | None = None,
        dest_tz: str | None = None,
    ):
        self.cents = cents
        self.arrival_time = arrival_time
        self.arrival_date = arrival_date
        self.dest_tz = dest_tz
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
                arrival_time=self.arrival_time,
                arrival_date=self.arrival_date,
                dest_tz=self.dest_tz,
            )
        ]


class _StubAward(AwardProvider):
    name = "stub_award"
    program_code = "AC"

    def __init__(
        self,
        points: int = 12500,
        arrival_time: time | None = None,
        arrival_date: date | None = None,
        dest_tz: str | None = None,
    ):
        self.points = points
        self.arrival_time = arrival_time
        self.arrival_date = arrival_date
        self.dest_tz = dest_tz
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
                arrival_time=self.arrival_time,
                arrival_date=self.arrival_date,
                dest_tz=self.dest_tz,
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


async def test_arrive_before_drops_late_arrivals(cache: TTLCache):
    cash = _StubCash(cents=30000)
    award = _StubAward(
        arrival_time=time(9, 30),
        arrival_date=date(2026, 6, 15),
        dest_tz="America/New_York",
    )
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert out.redemptions == []


async def test_arrive_before_keeps_early_arrivals(cache: TTLCache):
    cash = _StubCash(cents=30000)
    award = _StubAward(
        arrival_time=time(7, 13),  # JetBlue Mint case
        arrival_date=date(2026, 6, 15),
        dest_tz="America/New_York",
    )
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert len(out.redemptions) == 1


async def test_arrive_before_cross_tz_drops_late_jst_arrival(cache: TTLCache):
    """Tokyo-arriving offer landing 08:30 JST 2026-10-16 = 19:30 ET 2026-10-15.
    Filter '08:00ET' anchors cutoff to 2026-10-15 (the day the offer lands in
    ET), so 19:30 > 08:00 → drop. Catches the previous same-tz-only bug."""
    cash = _StubCash(cents=120_000)  # high cash -> good CPP
    award = _StubAward(
        arrival_time=time(8, 30),
        arrival_date=date(2026, 10, 16),
        dest_tz="Asia/Tokyo",
    )
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="NRT",
        depart_date=date(2026, 10, 15), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert out.redemptions == []


async def test_arrive_before_cross_tz_keeps_early_jst_arrival(cache: TTLCache):
    """Tokyo-arriving offer landing 20:30 JST 2026-10-16 = 07:30 ET 2026-10-16.
    Filter '08:00ET' anchors cutoff to 2026-10-16, so 07:30 < 08:00 → keep."""
    cash = _StubCash(cents=120_000)
    award = _StubAward(
        arrival_time=time(20, 30),
        arrival_date=date(2026, 10, 16),
        dest_tz="Asia/Tokyo",
    )
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="NRT",
        depart_date=date(2026, 10, 15), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert len(out.redemptions) == 1


async def test_arrive_before_no_dest_tz_falls_back_to_filter_tz(cache: TTLCache):
    """When dest_tz is absent the offer's arrival is interpreted in filter_tz,
    matching the prior same-tz behavior."""
    cash = _StubCash(cents=30_000)
    award = _StubAward(
        arrival_time=time(7, 13),
        arrival_date=date(2026, 6, 15),
        dest_tz=None,
    )
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert len(out.redemptions) == 1


async def test_arrive_before_keeps_chart_floor_results_without_times(cache: TTLCache):
    """Chart-floor providers populate no time fields; filter must keep them."""
    cash = _StubCash(cents=30000)
    award = _StubAward()  # no arrival fields — mimics StaticChartProvider output
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="06:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert len(out.redemptions) == 1


async def test_arrive_before_uses_cash_arrival_when_award_has_no_times(cache: TTLCache):
    """Chart-floor award (no times) + cash with arrival_time populated. Filter
    should fire against the cash side instead of passing through silently."""
    cash = _StubCash(
        cents=30_000,
        arrival_time=time(9, 30),
        arrival_date=date(2026, 6, 15),
        dest_tz="America/New_York",
    )
    award = _StubAward()  # no time fields, chart-floor analog
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert out.redemptions == []


async def test_arrive_before_keeps_when_cash_arrives_early_and_award_unset(cache: TTLCache):
    """Forcing-function scenario: cash arrives 05:25 ET 6/15, no award times.
    Filter '08:00ET' keeps the redemption."""
    cash = _StubCash(
        cents=30_000,
        arrival_time=time(5, 25),
        arrival_date=date(2026, 6, 15),
        dest_tz="America/New_York",
    )
    award = _StubAward()
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert len(out.redemptions) == 1


async def test_arrive_before_uses_earlier_of_award_and_cash_when_both_set(cache: TTLCache):
    """Award arrives 09:30 ET (would drop), cash arrives 07:13 ET (would keep).
    Using min() keeps the redemption — the user can still take the earlier of
    the two."""
    cash = _StubCash(
        cents=30_000,
        arrival_time=time(7, 13),
        arrival_date=date(2026, 6, 15),
        dest_tz="America/New_York",
    )
    award = _StubAward(
        arrival_time=time(9, 30),
        arrival_date=date(2026, 6, 15),
        dest_tz="America/New_York",
    )
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="08:00ET",
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert len(out.redemptions) == 1


async def test_arrive_before_unparseable_spec_warns_instead_of_failing(cache: TTLCache):
    cash = _StubCash(cents=30000)
    award = _StubAward(
        arrival_time=time(7, 13),
        arrival_date=date(2026, 6, 15),
        dest_tz="America/New_York",
    )
    orch = Orchestrator([cash], [award], cache)
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
        arrive_before_local="25:00ET",  # invalid HH
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    # Filter is skipped and the redemption survives; warning records the parse failure.
    assert len(out.redemptions) == 1
    assert any(
        "arrive-before filter disabled, returning unfiltered results" in w
        for w in out.warnings
    )


def test_parse_arrive_before_aliases() -> None:
    wall, tz = parse_arrive_before("08:00ET")
    assert wall == time(8, 0)
    assert str(tz) == "America/New_York"

    wall, tz = parse_arrive_before("14:30PT")
    assert wall == time(14, 30)
    assert str(tz) == "America/Los_Angeles"


def test_parse_arrive_before_rejects_bad_input() -> None:
    for bad in ("", "08:00", "8ET", "08:00XX", "25:00ET", "08:60ET"):
        with pytest.raises(ArriveBeforeParseError):
            parse_arrive_before(bad)


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
