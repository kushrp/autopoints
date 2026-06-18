from datetime import date

from autopoints.pricing.cpp import build_redemption
from autopoints.programs.loader import active_bonus
from autopoints.search.models import AwardOffer, Cabin, FlightOffer


def _cash() -> FlightOffer:
    return FlightOffer(
        provider="fast_flights",
        origin="JFK",
        destination="CDG",
        depart_date=date(2026, 6, 15),
        cabin=Cabin.economy,
        carrier="AF",
        cash_cents=80000,
    )


def _af_award(depart: date, points: int = 50000) -> AwardOffer:
    return AwardOffer(
        provider="AF",
        operating_carrier="AF",
        origin="JFK",
        destination="CDG",
        depart_date=depart,
        cabin=Cabin.economy,
        points=points,
        taxes_cents=20000,
    )


def test_mr_to_af_bonus_applies_in_window():
    # MR -> Flying Blue 25% bonus active 2026-06-01..2026-06-30 (transfer_bonuses.json).
    award = _af_award(date(2026, 6, 15), points=50000)
    r = build_redemption(_cash(), award, "MR", {"AF": 1.3}, cpp_great=2.0, cpp_good=1.5)
    assert r is not None
    assert r.points_required == 50000
    assert r.effective_points_required == round(50000 / 1.25)  # 40000
    assert any("25% transfer bonus" in note for note in r.notes)
    assert r.effective_cpp > r.cpp


def test_mr_to_af_bonus_absent_past_window():
    award = _af_award(date(2026, 8, 1), points=50000)
    r = build_redemption(_cash(), award, "MR", {"AF": 1.3}, cpp_great=2.0, cpp_good=1.5)
    assert r is not None
    assert r.effective_points_required == r.points_required


def test_loader_bonus_pairs_are_engine_compatible():
    # Both pairs exist in transfer_ratios.json, so active_bonus actually fires.
    assert active_bonus("UR", "VS", date(2026, 7, 10)) == 1.30
    assert active_bonus("MR", "AF", date(2026, 6, 15)) == 1.25
    # Past the UR->VS end (2026-07-14): no bonus.
    assert active_bonus("UR", "VS", date(2026, 7, 20)) == 1.0
