from __future__ import annotations

from datetime import date

import pytest

from autopoints.discord_bot.embeds import (
    COLOR_BAD,
    COLOR_GREAT,
    COLOR_NEUTRAL,
    search_results_embed,
    watchlist_list_embed,
    watchlist_run_embed,
)
from autopoints.search.models import AwardOffer, Cabin, FlightOffer, RedemptionResult
from autopoints.watchlists import Watchlist, WatchlistHit


def _redemption(cpp: float = 2.0, verdict: str = "great", program: str = "AC") -> RedemptionResult:
    cash = FlightOffer(
        provider="demo", origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
        carrier="UA", flight_numbers=["UA1"], cash_cents=30000,
    )
    award = AwardOffer(
        provider=program, operating_carrier="UA",
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), cabin=Cabin.economy,
        points=12500, taxes_cents=560,
    )
    return RedemptionResult(
        transfer_program="UR",
        points_program=program,
        points_required=12500,
        effective_points_required=12500,
        cash_offer=cash, award_offer=award,
        cpp=cpp, effective_cpp=cpp,
        valuation_cpp=1.5, verdict=verdict,  # type: ignore[arg-type]
        notes=["chart-floor only"],
    )


def _watchlist(label: str | None = None, threshold: float = 1.8) -> Watchlist:
    return Watchlist(
        id="abc12345",
        origin="JFK", destination="PHX",
        depart_date=date(2026, 6, 15), window_days=2,
        cabin=Cabin.economy, passengers=1,
        threshold_cpp=threshold, label=label,
        created_at=0.0,
    )


def test_search_embed_color_matches_top_verdict():
    e = search_results_embed("JFK", "PHX", "2026-06-15", 0, "economy", [_redemption(verdict="great")], [])
    assert e["color"] == COLOR_GREAT


def test_search_embed_no_redemptions_uses_neutral():
    e = search_results_embed("JFK", "PHX", "2026-06-15", 0, "economy", [], [])
    assert e["color"] == COLOR_NEUTRAL
    assert "No redemptions found" in e["description"]


def test_search_embed_caps_fields_at_10():
    redemptions = [_redemption(cpp=2.0 - i * 0.05) for i in range(15)]
    e = search_results_embed("JFK", "PHX", "2026-06-15", 0, "economy", redemptions, [])
    assert len(e["fields"]) == 10


def test_search_embed_renders_route_and_metadata():
    r = _redemption(cpp=2.5, verdict="great")
    e = search_results_embed("JFK", "PHX", "2026-06-15", 2, "economy", [r], [])
    assert e["title"] == "JFK → PHX"
    assert "2026-06-15" in e["description"]
    assert "± 2d" in e["description"]
    assert "economy" in e["description"]
    field = e["fields"][0]
    assert "UR" in field["name"] and "AC" in field["name"]
    assert "2.50¢" in field["name"]
    assert "12,500 pts" in field["value"]
    assert "chart-floor only" in field["value"]


def test_search_embed_appends_warnings():
    e = search_results_embed("JFK", "PHX", "2026-06-15", 0, "economy", [_redemption()], ["google_flights down"])
    warning_field = e["fields"][-1]
    assert "Warnings" in warning_field["name"]
    assert "google_flights down" in warning_field["value"]


def test_watchlist_list_embed_empty():
    e = watchlist_list_embed([])
    assert "No watchlists" in e["description"]
    assert e["fields"] == []


def test_watchlist_list_embed_populated():
    e = watchlist_list_embed([_watchlist(label="summer")])
    assert len(e["fields"]) == 1
    field = e["fields"][0]
    assert "abc12345" in field["name"]
    assert "JFK → PHX" in field["name"]
    assert "summer" in field["name"]
    assert "1.80¢" in field["value"]


def test_watchlist_run_embed_no_hits_when_only_new():
    wl = _watchlist()
    hits = [WatchlistHit(watchlist_id=wl.id, redemption=_redemption(), is_new=False)]
    e = watchlist_run_embed(wl, hits, only_new=True)
    assert "No hits" in e["description"]


def test_watchlist_run_embed_marks_new():
    wl = _watchlist(label="biz")
    hits = [
        WatchlistHit(watchlist_id=wl.id, redemption=_redemption(cpp=2.5), is_new=True),
        WatchlistHit(watchlist_id=wl.id, redemption=_redemption(cpp=2.0, program="BA"), is_new=False),
    ]
    e = watchlist_run_embed(wl, hits)
    assert "1 new" in e["description"]
    new_field = e["fields"][0]
    assert "🆕" in new_field["name"]
    old_field = e["fields"][1]
    assert "🆕" not in old_field["name"]


def test_watchlist_run_embed_bad_verdict_uses_red():
    wl = _watchlist()
    hits = [WatchlistHit(watchlist_id=wl.id, redemption=_redemption(verdict="bad"), is_new=True)]
    e = watchlist_run_embed(wl, hits)
    assert e["color"] == COLOR_BAD


def test_watchlist_run_embed_no_hits_with_warnings_surfaces_them():
    """U2 degraded result: hits=[] + warnings=[error text]. The embed must
    surface the warning and use a non-neutral color so the user notices the
    failed run vs a healthy zero-hit run."""
    wl = _watchlist()
    e = watchlist_run_embed(wl, hits=[], warnings=["watchlist run failed: RuntimeError('boom')"])
    assert e["color"] == COLOR_BAD
    assert "Run failed" in e["description"]
    assert any("⚠️ Warnings" in f["name"] and "boom" in f["value"] for f in e["fields"])


def test_watchlist_run_embed_with_hits_and_warnings_appends_warning_field():
    """A successful watchlist run that also carries warnings (e.g., U3's
    arrive-before parse failure) appends a warnings field after the hits."""
    wl = _watchlist()
    hits = [WatchlistHit(watchlist_id=wl.id, redemption=_redemption(cpp=2.5), is_new=True)]
    e = watchlist_run_embed(
        wl, hits, warnings=["arrive-before filter disabled, returning unfiltered results: 25:00XX"]
    )
    last_field = e["fields"][-1]
    assert "⚠️ Warnings" in last_field["name"]
    assert "filter disabled" in last_field["value"]


def test_watchlist_run_embed_no_warnings_omits_field():
    """Back-compat: existing calls without warnings produce no warnings field."""
    wl = _watchlist()
    hits = [WatchlistHit(watchlist_id=wl.id, redemption=_redemption(), is_new=True)]
    e = watchlist_run_embed(wl, hits)
    assert not any("Warnings" in f.get("name", "") for f in e.get("fields", []))


def test_bot_module_lazy_imports_discord():
    """The bot module imports cleanly even without discord.py installed.

    Discord is only imported inside make_bot(). This regression-guards the
    "discord.py is optional" contract."""
    from autopoints.discord_bot import bot
    assert callable(bot.make_bot)


def test_make_bot_requires_discord(monkeypatch):
    """Calling make_bot without discord.py installed gives a useful ImportError."""
    import sys
    # If discord IS installed in test env, skip this — the import-fails branch
    # is unreachable.
    if "discord" in sys.modules:
        pytest.skip("discord.py installed in test env")
    from autopoints.discord_bot import bot
    with pytest.raises(ImportError):
        bot.make_bot()
