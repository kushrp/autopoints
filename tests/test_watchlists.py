from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from autopoints.search.models import (
    AwardOffer,
    Cabin,
    FlightOffer,
    RedemptionResult,
)
from autopoints.watchlist_runner import run_one
from autopoints.watchlists import (
    WatchlistStore,
    filter_hits,
    format_hit_text,
    hit_signatures,
)


@pytest.fixture()
def store(tmp_path: Path) -> WatchlistStore:
    return WatchlistStore(tmp_path / "wl.db")


def _redemption(
    cpp: float = 2.0,
    points: int = 12500,
    program: str = "AC",
    transfer: str = "UR",
) -> RedemptionResult:
    cash = FlightOffer(
        provider="demo", origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
        carrier="UA", flight_numbers=["UA1"],
        cash_cents=int(points * cpp) + 560,
    )
    award = AwardOffer(
        provider=program, operating_carrier="UA",
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
        points=points, taxes_cents=560,
    )
    return RedemptionResult(
        transfer_program=transfer,  # type: ignore[arg-type]
        points_program=program,
        points_required=points,
        effective_points_required=points,
        cash_offer=cash, award_offer=award,
        cpp=cpp, effective_cpp=cpp,
        valuation_cpp=1.5, verdict="great",
    )


def test_add_list_remove(store: WatchlistStore):
    wl = store.add(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=2,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=1.8, label="summer",
    )
    assert wl.id
    assert wl.label == "summer"
    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == wl.id
    got = store.get(wl.id)
    assert got is not None and got.origin == "JFK"
    assert store.remove(wl.id) is True
    assert store.list() == []
    assert store.remove(wl.id) is False


def test_filter_hits_threshold(store: WatchlistStore):
    wl = store.add(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=0,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=2.0,
    )
    redemptions = [
        _redemption(cpp=1.5),    # below threshold
        _redemption(cpp=2.0),    # exactly at threshold
        _redemption(cpp=2.5, program="BA"),
    ]
    hits = filter_hits(wl, redemptions, seen_signatures=set())
    assert len(hits) == 2
    assert all(h.is_new for h in hits)


def test_diff_marks_seen_as_not_new(store: WatchlistStore):
    wl = store.add(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=0,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=1.0,
    )
    r = _redemption(cpp=2.5)
    hits = filter_hits(wl, [r], seen_signatures=set())
    assert hits[0].is_new
    store.record_seen(wl.id, hit_signatures(hits))

    hits2 = filter_hits(wl, [r], seen_signatures=store.seen_signatures(wl.id))
    assert not hits2[0].is_new

    # A new program at the same threshold IS new.
    other = _redemption(cpp=2.5, program="BA")
    hits3 = filter_hits(wl, [r, other], seen_signatures=store.seen_signatures(wl.id))
    by_program = {h.redemption.points_program: h.is_new for h in hits3}
    assert by_program == {"AC": False, "BA": True}


def test_format_hit_text(store: WatchlistStore):
    wl = store.add(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=0,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=2.0, label="trip",
    )
    hits = filter_hits(wl, [_redemption(cpp=2.5)], seen_signatures=set())
    text = format_hit_text(hits[0], wl)
    assert "NEW" in text and "JFK→PHX" in text and "[trip]" in text and "2.50cpp" in text


def test_run_one_demo_mode_persists_signatures(store: WatchlistStore):
    wl = store.add(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=0,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=1.0,
    )
    result1 = asyncio.run(run_one(wl, store, demo=True))
    assert len(result1.hits) > 0
    assert all(h.is_new for h in result1.hits)

    result2 = asyncio.run(run_one(wl, store, demo=True))
    assert len(result2.hits) == len(result1.hits)
    assert all(not h.is_new for h in result2.hits)
