"""Pure functions that build Discord embed payloads.

Returning plain dicts (Discord embed shape) instead of discord.Embed objects
keeps this module importable without the discord.py dep, and lets us unit-test
the formatting against expected JSON.
"""

from __future__ import annotations

from typing import Iterable

from autopoints.search.models import RedemptionResult
from autopoints.watchlists import Watchlist, WatchlistHit

# Discord embed colors (RGB int)
COLOR_GREAT = 0x2ECC71
COLOR_GOOD = 0x3498DB
COLOR_OK = 0xF1C40F
COLOR_BAD = 0xE74C3C
COLOR_NEUTRAL = 0x95A5A6

VERDICT_COLOR = {
    "great": COLOR_GREAT,
    "good": COLOR_GOOD,
    "ok": COLOR_OK,
    "bad": COLOR_BAD,
}


def search_results_embed(
    origin: str,
    destination: str,
    depart_date: str,
    window_days: int,
    cabin: str,
    redemptions: list[RedemptionResult],
    warnings: list[str],
) -> dict:
    title = f"{origin} → {destination}"
    desc_parts = [f"**{depart_date}**"]
    if window_days:
        desc_parts.append(f"± {window_days}d")
    desc_parts.append(f"`{cabin}`")
    description = "  ".join(desc_parts)

    top_color = VERDICT_COLOR.get(redemptions[0].verdict, COLOR_NEUTRAL) if redemptions else COLOR_NEUTRAL

    fields: list[dict] = []
    for r in redemptions[:10]:  # Discord caps fields at 25; 10 is plenty
        name = (
            f"{r.transfer_program} → {r.points_program}  "
            f"**{r.effective_cpp:.2f}¢**  [{r.verdict}]"
        )
        value = (
            f"{r.points_required:,} pts  "
            f"+${r.award_offer.taxes_cents / 100:.2f} tax  "
            f"vs ${r.cash_offer.cash_cents / 100:.2f} cash  "
            f"({r.award_offer.depart_date.isoformat()})"
        )
        if r.notes:
            value += f"\n_{r.notes[0]}_"
        fields.append({"name": name, "value": value, "inline": False})

    embed: dict = {
        "title": title,
        "description": description,
        "color": top_color,
        "fields": fields,
        "footer": {"text": "autopoints • CPP = (cash − taxes) ÷ points"},
    }
    if warnings:
        embed["fields"].append({
            "name": "⚠️ Warnings",
            "value": "\n".join(f"• {w}" for w in warnings[:5]),
            "inline": False,
        })
    if not redemptions:
        embed["description"] += "\n\n_No redemptions found._"
    return embed


def watchlist_list_embed(watchlists: Iterable[Watchlist]) -> dict:
    rows: list[dict] = []
    for wl in watchlists:
        name = f"`{wl.id}`  {wl.origin} → {wl.destination}"
        if wl.label:
            name += f"  · {wl.label}"
        value = (
            f"{wl.depart_date} ±{wl.window_days}d  "
            f"`{wl.cabin.value}`  "
            f"threshold **{wl.threshold_cpp:.2f}¢**"
        )
        rows.append({"name": name, "value": value, "inline": False})

    return {
        "title": "Watchlists",
        "description": "Use `/watchlist remove id:<id>` to delete." if rows else "No watchlists yet. Use `/watchlist add` to create one.",
        "color": COLOR_NEUTRAL,
        "fields": rows,
    }


def watchlist_run_embed(
    watchlist: Watchlist,
    hits: list[WatchlistHit],
    only_new: bool = False,
) -> dict:
    filtered = [h for h in hits if h.is_new] if only_new else hits
    title = f"{watchlist.origin} → {watchlist.destination}"
    if watchlist.label:
        title += f"  · {watchlist.label}"

    if not filtered:
        return {
            "title": title,
            "description": "_No hits above threshold._" if only_new else "_No hits above threshold this run._",
            "color": COLOR_NEUTRAL,
            "footer": {"text": f"threshold {watchlist.threshold_cpp:.2f}¢"},
        }

    color = VERDICT_COLOR.get(filtered[0].redemption.verdict, COLOR_NEUTRAL)
    fields: list[dict] = []
    for h in filtered[:10]:
        r = h.redemption
        tag = "🆕 " if h.is_new else ""
        name = (
            f"{tag}{r.transfer_program} → {r.points_program}  "
            f"**{r.effective_cpp:.2f}¢**  [{r.verdict}]"
        )
        value = (
            f"{r.points_required:,} pts  "
            f"+${r.award_offer.taxes_cents / 100:.2f} tax  "
            f"vs ${r.cash_offer.cash_cents / 100:.2f} cash  "
            f"({r.award_offer.depart_date.isoformat()})"
        )
        fields.append({"name": name, "value": value, "inline": False})

    new_count = sum(1 for h in filtered if h.is_new)
    return {
        "title": title,
        "description": f"**{new_count} new** / {len(filtered)} total hits above {watchlist.threshold_cpp:.2f}¢",
        "color": color,
        "fields": fields,
    }
