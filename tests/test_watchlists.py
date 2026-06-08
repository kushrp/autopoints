from __future__ import annotations

import asyncio
import sqlite3
from datetime import date, time
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
    _signature,
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
    arrival_time: time | None = None,
    arrival_date: date | None = None,
) -> RedemptionResult:
    cash = FlightOffer(
        provider="demo", origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
        carrier="UA", flight_numbers=["UA1"],
        cash_cents=int(points * cpp) + 560,
        arrival_time=arrival_time, arrival_date=arrival_date,
    )
    award = AwardOffer(
        provider=program, operating_carrier="UA",
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
        points=points, taxes_cents=560,
        arrival_time=arrival_time, arrival_date=arrival_date,
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


def test_signature_distinguishes_redeyes_with_different_arrival_times():
    early = _redemption(arrival_time=time(5, 25), arrival_date=date(2026, 6, 16))
    late = _redemption(arrival_time=time(7, 13), arrival_date=date(2026, 6, 16))
    assert _signature(early) != _signature(late)


def test_signature_back_compat_when_arrival_fields_unset():
    # Signature without arrival fields must match the pre-migration shape so
    # rows in `watchlist_seen` written before the schema migration keep their
    # identity. The first call has no time data; the second has only one of
    # the two required fields. Both must collapse to the base signature.
    base = _redemption()
    partial = _redemption(arrival_time=time(7, 13), arrival_date=None)
    assert _signature(base) == _signature(partial)


def test_store_init_is_idempotent_for_arrive_before_migration(tmp_path: Path):
    path = tmp_path / "wl.db"
    # Simulate a pre-migration database created without `arrive_before_local`.
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE watchlists ("
            "id TEXT PRIMARY KEY, origin TEXT, destination TEXT, "
            "depart_date TEXT, window_days INTEGER, cabin TEXT, "
            "passengers INTEGER, threshold_cpp REAL, label TEXT, created_at REAL)"
        )
        conn.execute(
            "INSERT INTO watchlists VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy", "JFK", "PHX", "2026-06-15", 0, "economy", 1, 1.8, "old", 1717718400.0),
        )
        conn.commit()

    # Two successive WatchlistStore initializations must not error and must
    # leave the legacy row readable with arrive_before_local=None.
    WatchlistStore(path)
    store = WatchlistStore(path)

    legacy = store.get("legacy")
    assert legacy is not None
    assert legacy.arrive_before_local is None


def test_add_persists_arrive_before_local(store: WatchlistStore):
    wl = store.add(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=0,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=1.8, arrive_before_local="08:00ET",
    )
    fetched = store.get(wl.id)
    assert fetched is not None
    assert fetched.arrive_before_local == "08:00ET"
    assert fetched.to_search_request().arrive_before_local == "08:00ET"


def test_run_all_continues_when_one_watchlist_raises(
    store: WatchlistStore, monkeypatch: pytest.MonkeyPatch
):
    """A single watchlist's run failure must not cancel sibling runs.

    Two watchlists added; mock run_one to raise for the first and succeed for
    the second. run_all must return 2 results: first is a degraded
    WatchlistRunResult with empty hits + a warning, second is normal.
    """
    from autopoints import watchlist_runner

    store.add(
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=0,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=1.0, label="failing",
    )
    store.add(
        origin="LAX", destination="ORD",
        depart_date=date(2026, 6, 15), window_days=0,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=1.0, label="ok",
    )

    call_log: list[str] = []

    async def fake_run_one(wl, _store, **_kw):
        call_log.append(wl.label)
        if wl.label == "failing":
            raise RuntimeError("boom")
        from autopoints.watchlists import WatchlistRunResult
        return WatchlistRunResult(watchlist=wl, hits=[], warnings=[])

    monkeypatch.setattr(watchlist_runner, "run_one", fake_run_one)

    results = asyncio.run(watchlist_runner.run_all(store))
    assert len(results) == 2
    by_label = {r.watchlist.label: r for r in results}
    assert by_label["failing"].hits == []
    assert any("watchlist run failed" in w and "boom" in w for w in by_label["failing"].warnings)
    assert by_label["ok"].hits == []
    assert by_label["ok"].warnings == []
    # Both watchlists were attempted.
    assert sorted(call_log) == ["failing", "ok"]


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
