"""Metro-area code expansion.

Travelers think in cities (NYC, LON) — IATA thinks in airports. This module
maps the metro codes that real people type into the airport lists that
providers actually query. Keep the mapping conservative: only add entries
where every airport in the list serves the same metro and is a normal
substitute for travel intent.

Lowercase/uppercase both work; we normalize to upper.

Order within a list matters: the first airport is the "primary" one that
single-airport callers (e.g. legacy watchlist entries) get when they hand
us a metro code. For NYC that's JFK because long-haul and award redemptions
preferentially route there.
"""

from __future__ import annotations

# IATA itself has "metropolitan area codes" for some cities (NYC, LON, etc.).
# We extend with a few US metros that lack official codes but where multi-
# airport comparison is the default mental model.
_METRO_AIRPORTS: dict[str, tuple[str, ...]] = {
    "NYC": ("JFK", "LGA", "EWR"),
    "LON": ("LHR", "LGW", "STN", "LCY"),
    "CHI": ("ORD", "MDW"),
    "WAS": ("DCA", "IAD", "BWI"),
    "BAY": ("SFO", "OAK", "SJC"),
    "LAA": ("LAX", "BUR", "LGB", "SNA"),
    "MIA": ("MIA", "FLL", "PBI"),
    "HOU": ("IAH", "HOU"),
    "DAL": ("DFW", "DAL"),
    "TYO": ("HND", "NRT"),
    "PAR": ("CDG", "ORY"),
}


def expand(code: str) -> list[str]:
    """Return the airport list for `code`. If `code` is a regular IATA airport
    (not a metro), returns [code] unchanged.

    The single-airport pass-through is what lets the CLI accept either form
    interchangeably — `LAX` and `LAA` both work, the latter just fans out.
    """
    normalized = code.strip().upper()
    if normalized in _METRO_AIRPORTS:
        return list(_METRO_AIRPORTS[normalized])
    return [normalized]


def is_metro(code: str) -> bool:
    return code.strip().upper() in _METRO_AIRPORTS


def known_metros() -> dict[str, tuple[str, ...]]:
    """Snapshot of all configured metro mappings — for help text and tests."""
    return dict(_METRO_AIRPORTS)
