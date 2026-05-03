from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from importlib.resources import files
from typing import Any


def _load_json(name: str) -> dict[str, Any]:
    path = files("autopoints.programs").joinpath(name)
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def transfer_ratios() -> dict[str, dict[str, float]]:
    data = _load_json("transfer_ratios.json")
    return {k: v for k, v in data.items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def valuations() -> dict[str, float]:
    data = _load_json("valuations.json")
    return {k: v for k, v in data.items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def transfer_bonuses() -> list[dict[str, Any]]:
    return _load_json("transfer_bonuses.json").get("active", [])


def active_bonus(from_currency: str, to_program: str, on_date: date) -> float:
    """Returns multiplier for an active transfer bonus, or 1.0 if none.
    1.3 = 30% bonus: 1000 currency points becomes 1300 program miles."""
    on_iso = on_date.isoformat()
    for bonus in transfer_bonuses():
        if bonus.get("from") != from_currency or bonus.get("to") != to_program:
            continue
        if bonus.get("start", "0000-01-01") <= on_iso <= bonus.get("end", "9999-12-31"):
            return float(bonus.get("multiplier", 1.0))
    return 1.0


def award_chart(program: str) -> dict[str, Any]:
    return _load_json(f"award_charts/{program.lower()}.json")
