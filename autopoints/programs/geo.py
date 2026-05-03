from __future__ import annotations

import math
from functools import lru_cache

from autopoints.programs.loader import _load_json


@lru_cache(maxsize=1)
def _airports() -> dict[str, dict]:
    data = _load_json("airports.json")
    return {k: v for k, v in data.items() if not k.startswith("_")}


def airport(code: str) -> dict | None:
    return _airports().get(code.upper())


def haversine_miles(orig: str, dest: str) -> float:
    a = airport(orig)
    b = airport(dest)
    if a is None or b is None:
        raise KeyError(
            f"Airport not in database: {orig if a is None else dest}. "
            f"Add it to autopoints/programs/airports.json."
        )
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    # Earth radius in statute miles (Aeroplan's chart uses statute miles).
    return 2 * 3958.7613 * math.asin(math.sqrt(h))
