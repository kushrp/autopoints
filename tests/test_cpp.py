from datetime import date

from autopoints.pricing.cpp import (
    build_redemption,
    compute_cpp,
    points_required_via_transfer,
)
from autopoints.search.models import AwardOffer, Cabin, FlightOffer


def test_compute_cpp_basic():
    # $180 cash, $5.60 taxes, 12500 points -> 1.3952 cpp
    assert round(compute_cpp(18000, 560, 12500), 4) == 1.3952


def test_compute_cpp_great_redemption():
    # $300 cash -> 2.3552 cpp
    assert round(compute_cpp(30000, 560, 12500), 4) == 2.3552


def test_compute_cpp_zero_points():
    assert compute_cpp(10000, 0, 0) == 0.0


def test_compute_cpp_clamps_negative():
    # Taxes higher than cash shouldn't yield negative CPP.
    assert compute_cpp(500, 1000, 10000) == 0.0


def test_transfer_ratios_one_to_one():
    # UR -> Aeroplan is 1:1
    assert points_required_via_transfer(12500, "UR", "AC") == 12500


def test_transfer_ratios_unknown_pair():
    assert points_required_via_transfer(12500, "UR", "ZZ") is None


def test_transfer_ratios_aeromexico_mr():
    # MR -> Aeromexico is 1.6:1, so 1000 award miles needs 1600 MR.
    assert points_required_via_transfer(1000, "MR", "AM") == 1600


def _cash() -> FlightOffer:
    return FlightOffer(
        provider="google_flights",
        origin="JFK",
        destination="PHX",
        depart_date=date(2026, 6, 15),
        cabin=Cabin.economy,
        carrier="UA",
        flight_numbers=["UA1234"],
        cash_cents=18000,
    )


def _award(points: int = 12500, taxes_cents: int = 560) -> AwardOffer:
    return AwardOffer(
        provider="AC",
        operating_carrier="UA",
        origin="JFK",
        destination="PHX",
        depart_date=date(2026, 6, 15),
        cabin=Cabin.economy,
        points=points,
        taxes_cents=taxes_cents,
    )


def test_build_redemption_meh_verdict():
    r = build_redemption(_cash(), _award(), "UR", {"AC": 1.5}, cpp_great=2.0, cpp_good=1.5)
    assert r is not None
    assert r.points_required == 12500
    assert round(r.cpp, 2) == 1.40
    # 1.40 < valuation 1.5 -> bad
    assert r.verdict == "bad"


def test_build_redemption_good_verdict():
    cash = _cash().model_copy(update={"cash_cents": 25000})
    r = build_redemption(cash, _award(), "UR", {"AC": 1.5}, cpp_great=2.0, cpp_good=1.5)
    assert r is not None
    assert round(r.cpp, 2) == 1.96
    assert r.verdict == "good"


def test_build_redemption_great_verdict():
    cash = _cash().model_copy(update={"cash_cents": 30000})
    r = build_redemption(cash, _award(), "UR", {"AC": 1.5}, cpp_great=2.0, cpp_good=1.5)
    assert r is not None
    assert r.verdict == "great"


def test_build_redemption_returns_none_for_unsupported_transfer():
    # DIRECT->ZZ not in ratios
    award = _award().model_copy(update={"provider": "ZZ"})
    r = build_redemption(_cash(), award, "DIRECT", {}, cpp_great=2.0, cpp_good=1.5)
    assert r is None


def test_build_redemption_chart_floor_note():
    # operating_carrier "**" indicates chart-floor pricing
    award = _award().model_copy(update={"operating_carrier": "**"})
    r = build_redemption(_cash(), award, "UR", {"AC": 1.5}, cpp_great=2.0, cpp_good=1.5)
    assert r is not None
    assert any("chart-floor" in n for n in r.notes)
