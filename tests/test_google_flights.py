"""Unit tests for the Google Flights cash provider.

`fli` calls Google's backend directly (not via httpx), so respx can't intercept
it. We patch the `_search_sync` shim instead — proves the provider's adapter
logic without hitting live network. Tests marked `@pytest.mark.e2e` exercise
the live path; they're excluded by default `addopts = "-m 'not e2e'"`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, time
from types import SimpleNamespace
from typing import Any

import pytest

from autopoints.providers import google_flights as gf
from autopoints.providers.base import ProviderError
from autopoints.search.models import Cabin


def _leg(
    airline_code: str,
    flight_number: int,
    dep: datetime,
    arr: datetime,
) -> SimpleNamespace:
    return SimpleNamespace(
        airline=SimpleNamespace(name=airline_code),
        flight_number=flight_number,
        departure_datetime=dep,
        arrival_datetime=arr,
    )


def _result(
    price: float, legs: list[SimpleNamespace], duration: int, stops: int
) -> SimpleNamespace:
    return SimpleNamespace(price=price, legs=legs, duration=duration, stops=stops)


PatchSearch = Callable[[Any], None]


@pytest.fixture()
def patch_search(monkeypatch: pytest.MonkeyPatch) -> PatchSearch:
    def _patch(results: Any) -> None:
        def fake(*_a: Any, **_kw: Any) -> Any:
            return results

        monkeypatch.setattr(gf, "_search_sync", fake)

    return _patch


def test_nonstop_redeye_maps_to_flight_offer(patch_search: PatchSearch) -> None:
    """B6 1024 LAX 22:25 → JFK 07:13 next day, $409 — the validated probe case."""
    legs = [
        _leg(
            "B6",
            1024,
            datetime(2026, 6, 14, 22, 25),
            datetime(2026, 6, 15, 7, 13),
        )
    ]
    patch_search([_result(409.0, legs, duration=348, stops=0)])

    offers = asyncio.run(
        gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
    )
    assert len(offers) == 1
    o = offers[0]
    assert o.provider == "google_flights"
    assert o.carrier == "B6"
    assert o.flight_numbers == ["B61024"]
    assert o.cash_cents == 40900
    assert o.currency == "USD"
    assert o.stops == 0
    assert o.duration_minutes == 348
    assert o.departure_time == time(22, 25)
    assert o.arrival_time == time(7, 13)
    assert o.arrival_date == date(2026, 6, 15)


def test_multi_leg_uses_first_leg_departure_last_leg_arrival(patch_search: PatchSearch) -> None:
    """AA 1362+1587 LAX → PHX → JFK, two legs concatenated."""
    legs = [
        _leg("AA", 1362, datetime(2026, 6, 14, 19, 30), datetime(2026, 6, 14, 21, 3)),
        _leg("AA", 1587, datetime(2026, 6, 14, 21, 53), datetime(2026, 6, 15, 5, 44)),
    ]
    patch_search([_result(357.0, legs, duration=434, stops=1)])

    offers = asyncio.run(
        gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
    )
    assert len(offers) == 1
    o = offers[0]
    assert o.carrier == "AA"
    assert o.flight_numbers == ["AA1362", "AA1587"]
    assert o.cash_cents == 35700
    assert o.stops == 1
    assert o.departure_time == time(19, 30)
    assert o.arrival_time == time(5, 44)
    assert o.arrival_date == date(2026, 6, 15)


def test_empty_results_returns_empty_list(patch_search: PatchSearch) -> None:
    patch_search([])
    offers = asyncio.run(
        gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
    )
    assert offers == []


def test_none_results_returns_empty_list(patch_search: PatchSearch) -> None:
    """fli returns None when no flights match."""
    patch_search(None)
    offers = asyncio.run(
        gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
    )
    assert offers == []


def test_round_trip_tuples_are_skipped(patch_search: PatchSearch) -> None:
    """Round-trip results come back as tuples; one-way path skips them."""
    legs = [_leg("DL", 960, datetime(2026, 6, 14, 21, 10), datetime(2026, 6, 15, 5, 25))]
    patch_search([(_result(539.0, legs, 315, 0), _result(539.0, legs, 315, 0))])
    offers = asyncio.run(
        gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
    )
    assert offers == []


def test_malformed_row_is_skipped_not_raised(patch_search: PatchSearch) -> None:
    """Parser drops unparseable rows without breaking the rest of the batch."""
    bad = SimpleNamespace(price=None, legs=[])  # missing/bad price + empty legs
    good_legs = [_leg("UA", 4, datetime(2026, 6, 14, 21, 30), datetime(2026, 6, 15, 5, 55))]
    good = _result(199.0, good_legs, 325, 0)

    patch_search([bad, good])
    offers = asyncio.run(
        gf.GoogleFlightsProvider().search("LAX", "EWR", date(2026, 6, 14), Cabin.economy)
    )
    assert len(offers) == 1
    assert offers[0].carrier == "UA"
    assert offers[0].cash_cents == 19900


def test_upstream_exception_wraps_to_provider_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Any non-ProviderError exception from _search_sync wraps to ProviderError
    AND emits a logger.exception call so persistent failure is operator-visible."""
    def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("fli crashed")

    monkeypatch.setattr(gf, "_search_sync", boom)
    with caplog.at_level("ERROR", logger="autopoints.providers.google_flights"):
        with pytest.raises(ProviderError) as exc:
            asyncio.run(
                gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
            )
    assert "google_flights" in str(exc.value)
    # logger.exception emits at ERROR with the traceback attached. Asserting
    # exc_info pins the .exception() call over .error() — a mutation to
    # logger.error would still pass the level check but lose the traceback.
    records = [r for r in caplog.records if r.name == "autopoints.providers.google_flights"]
    assert any(
        r.levelname == "ERROR" and "fli search failed" in r.message and r.exc_info is not None
        for r in records
    )


def test_provider_error_passes_through(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """ProviderError raised from _search_sync (e.g. missing fli install) is not
    re-wrapped — and the broad-catch logger.exception branch is NOT entered."""
    def missing(*_a: Any, **_kw: Any) -> Any:
        raise ProviderError("google_flights: `flights` package not installed.")

    monkeypatch.setattr(gf, "_search_sync", missing)
    with caplog.at_level("ERROR", logger="autopoints.providers.google_flights"):
        with pytest.raises(ProviderError, match="not installed"):
            asyncio.run(
                gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
            )
    records = [r for r in caplog.records if r.name == "autopoints.providers.google_flights"]
    assert records == []


def test_unknown_airport_raises_provider_error() -> None:
    """Real fli Airport enum doesn't include arbitrary codes — should error cleanly."""
    with pytest.raises(ProviderError, match="unsupported airport"):
        asyncio.run(
            gf.GoogleFlightsProvider().search("XXX", "JFK", date(2026, 6, 14), Cabin.economy)
        )


@pytest.mark.e2e
def test_live_lax_jfk_returns_redeye() -> None:
    """Smoke test against the live Google Flights backend. Marked e2e so the
    default suite skips it. Asserts the basic shape of the validated probe."""
    offers = asyncio.run(
        gf.GoogleFlightsProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)
    )
    assert offers, "live fli call returned no offers"
    redeyes = [o for o in offers if o.arrival_date and o.arrival_date > date(2026, 6, 14)]
    assert redeyes, "no redeye options found (expected at least JetBlue / Delta)"
    for o in redeyes:
        assert o.carrier
        assert o.cash_cents > 0
        assert o.departure_time is not None
        assert o.arrival_time is not None
