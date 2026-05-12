"""Watchlist storage and the run-with-diff loop.

A watchlist is a saved SearchRequest plus a CPP threshold. Running it executes
the search and, if any redemption beats the threshold, returns the "interesting"
rows along with whether each is new since the last run.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator

from autopoints.search.models import Cabin, RedemptionResult, SearchRequest


@dataclass
class Watchlist:
    id: str
    origin: str
    destination: str
    depart_date: date
    window_days: int
    cabin: Cabin
    passengers: int
    threshold_cpp: float
    created_at: float
    label: str | None = None

    def to_search_request(self) -> SearchRequest:
        return SearchRequest(
            origin=self.origin,
            destination=self.destination,
            depart_date=self.depart_date,
            window_days=self.window_days,
            cabin=self.cabin,
            passengers=self.passengers,
        )


@dataclass
class WatchlistHit:
    watchlist_id: str
    redemption: RedemptionResult
    is_new: bool  # not seen in the previous run


@dataclass
class WatchlistRunResult:
    watchlist: Watchlist
    hits: list[WatchlistHit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _signature(r: RedemptionResult) -> str:
    """Identity for diffing: same redemption row across runs collapses to one key."""
    return (
        f"{r.transfer_program}|{r.points_program}|{r.award_offer.depart_date.isoformat()}"
        f"|{r.award_offer.cabin.value}|{r.award_offer.operating_carrier}"
        f"|{r.points_required}"
    )


class WatchlistStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS watchlists ("
                "id TEXT PRIMARY KEY, "
                "origin TEXT NOT NULL, "
                "destination TEXT NOT NULL, "
                "depart_date TEXT NOT NULL, "
                "window_days INTEGER NOT NULL, "
                "cabin TEXT NOT NULL, "
                "passengers INTEGER NOT NULL, "
                "threshold_cpp REAL NOT NULL, "
                "label TEXT, "
                "created_at REAL NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS watchlist_seen ("
                "watchlist_id TEXT NOT NULL, "
                "signature TEXT NOT NULL, "
                "first_seen_at REAL NOT NULL, "
                "PRIMARY KEY (watchlist_id, signature))"
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        window_days: int,
        cabin: Cabin,
        passengers: int,
        threshold_cpp: float,
        label: str | None = None,
    ) -> Watchlist:
        wl = Watchlist(
            id=uuid.uuid4().hex[:8],
            origin=origin.upper(),
            destination=destination.upper(),
            depart_date=depart_date,
            window_days=window_days,
            cabin=cabin,
            passengers=passengers,
            threshold_cpp=threshold_cpp,
            created_at=time.time(),
            label=label,
        )
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO watchlists VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    wl.id, wl.origin, wl.destination, wl.depart_date.isoformat(),
                    wl.window_days, wl.cabin.value, wl.passengers, wl.threshold_cpp,
                    wl.label, wl.created_at,
                ),
            )
        return wl

    def list(self) -> list[Watchlist]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM watchlists ORDER BY created_at DESC").fetchall()
        return [_row_to_watchlist(r) for r in rows]

    def get(self, id_: str) -> Watchlist | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM watchlists WHERE id = ?", (id_,)).fetchone()
        return _row_to_watchlist(row) if row else None

    def remove(self, id_: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM watchlists WHERE id = ?", (id_,))
            conn.execute("DELETE FROM watchlist_seen WHERE watchlist_id = ?", (id_,))
            return cur.rowcount > 0

    def seen_signatures(self, watchlist_id: str) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT signature FROM watchlist_seen WHERE watchlist_id = ?",
                (watchlist_id,),
            ).fetchall()
        return {r[0] for r in rows}

    def record_seen(self, watchlist_id: str, signatures: list[str]) -> None:
        if not signatures:
            return
        now = time.time()
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO watchlist_seen VALUES (?, ?, ?)",
                [(watchlist_id, s, now) for s in signatures],
            )


def _row_to_watchlist(row: tuple) -> Watchlist:
    return Watchlist(
        id=row[0],
        origin=row[1],
        destination=row[2],
        depart_date=date.fromisoformat(row[3]),
        window_days=row[4],
        cabin=Cabin(row[5]),
        passengers=row[6],
        threshold_cpp=row[7],
        label=row[8],
        created_at=row[9],
    )


def filter_hits(
    watchlist: Watchlist,
    redemptions: list[RedemptionResult],
    seen_signatures: set[str],
) -> list[WatchlistHit]:
    """Return redemptions meeting the watchlist's threshold, marked new vs. previously-seen."""
    hits: list[WatchlistHit] = []
    for r in redemptions:
        if r.effective_cpp < watchlist.threshold_cpp:
            continue
        sig = _signature(r)
        hits.append(
            WatchlistHit(
                watchlist_id=watchlist.id,
                redemption=r,
                is_new=sig not in seen_signatures,
            )
        )
    return hits


def hit_signatures(hits: list[WatchlistHit]) -> list[str]:
    return [_signature(h.redemption) for h in hits]


def format_hit_text(hit: WatchlistHit, watchlist: Watchlist) -> str:
    r = hit.redemption
    tag = "NEW" if hit.is_new else "still"
    label = f" [{watchlist.label}]" if watchlist.label else ""
    return (
        f"{tag} {watchlist.origin}→{watchlist.destination}{label} "
        f"{r.award_offer.depart_date.isoformat()}: "
        f"{r.points_required:,} {r.points_program} pts ({r.transfer_program}) "
        f"vs ${r.cash_offer.cash_cents / 100:.2f} cash = "
        f"{r.effective_cpp:.2f}cpp [{r.verdict}]"
    )


def webhook_payload(result: WatchlistRunResult) -> dict:
    """Build a JSON payload suitable for any webhook (Discord/Slack/generic)."""
    return {
        "watchlist": {
            "id": result.watchlist.id,
            "label": result.watchlist.label,
            "route": f"{result.watchlist.origin} → {result.watchlist.destination}",
            "depart_date": result.watchlist.depart_date.isoformat(),
            "window_days": result.watchlist.window_days,
            "threshold_cpp": result.watchlist.threshold_cpp,
        },
        "hits": [
            {
                "is_new": h.is_new,
                "transfer_program": h.redemption.transfer_program,
                "points_program": h.redemption.points_program,
                "points_required": h.redemption.points_required,
                "effective_cpp": h.redemption.effective_cpp,
                "verdict": h.redemption.verdict,
                "depart_date": h.redemption.award_offer.depart_date.isoformat(),
                "cash_cents": h.redemption.cash_offer.cash_cents,
            }
            for h in result.hits
        ],
        "warnings": result.warnings,
    }


__all__ = [
    "Watchlist",
    "WatchlistHit",
    "WatchlistRunResult",
    "WatchlistStore",
    "filter_hits",
    "hit_signatures",
    "format_hit_text",
    "webhook_payload",
]
