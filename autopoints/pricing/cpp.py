from __future__ import annotations

from typing import Literal

from autopoints.programs.loader import active_bonus, transfer_ratios
from autopoints.search.models import AwardOffer, FlightOffer, RedemptionResult

TransferProgram = Literal["UR", "MR", "DIRECT"]


def compute_cpp(cash_cents: int, taxes_cents: int, points: int) -> float:
    if points <= 0:
        return 0.0
    return max(0.0, (cash_cents - taxes_cents) / points)


def points_required_via_transfer(
    award_points: int, from_currency: TransferProgram, to_program: str
) -> int | None:
    """Return how many `from_currency` points must be transferred to cover the
    award. None if the transfer pair isn't supported."""
    ratios = transfer_ratios().get(from_currency, {})
    ratio = ratios.get(to_program)
    if ratio is None:
        return None
    # ratio means "X currency points = 1 partner mile". Need points / (1/ratio) = points * ratio.
    # In our JSON, all current pairs are 1.0 except MR->Aeromexico (1.6 MR = 1 Aeromexico mile).
    return int(round(award_points * ratio))


def build_redemption(
    cash: FlightOffer,
    award: AwardOffer,
    from_currency: TransferProgram,
    valuations: dict[str, float],
    cpp_great: float,
    cpp_good: float,
) -> RedemptionResult | None:
    points = points_required_via_transfer(award.points, from_currency, award.provider)
    if points is None:
        return None

    bonus_multiplier = active_bonus(from_currency, award.provider, award.depart_date)
    effective_points = int(round(points / bonus_multiplier)) if bonus_multiplier else points

    cpp = compute_cpp(cash.cash_cents, award.taxes_cents, points)
    effective_cpp = compute_cpp(cash.cash_cents, award.taxes_cents, effective_points)
    valuation = valuations.get(award.provider, 1.0)

    verdict = _verdict(effective_cpp, valuation, cpp_great, cpp_good)

    notes: list[str] = []
    if award.taxes_currency != "USD":
        notes.append(f"taxes returned in {award.taxes_currency}; CPP assumes 1:1 to USD — verify")
    if award.operating_carrier == "**":
        notes.append("chart-floor pricing only; live availability not confirmed")
    if bonus_multiplier > 1.0:
        notes.append(f"includes {int((bonus_multiplier - 1) * 100)}% transfer bonus")

    return RedemptionResult(
        transfer_program=from_currency,
        points_program=award.provider,
        points_required=points,
        effective_points_required=effective_points,
        cash_offer=cash,
        award_offer=award,
        cpp=cpp,
        effective_cpp=effective_cpp,
        valuation_cpp=valuation,
        verdict=verdict,
        notes=notes,
    )


def _verdict(
    effective_cpp: float, valuation: float, cpp_great: float, cpp_good: float
) -> Literal["great", "good", "ok", "bad"]:
    if effective_cpp >= cpp_great:
        return "great"
    if effective_cpp >= cpp_good:
        return "good"
    if effective_cpp >= valuation:
        return "ok"
    return "bad"
