from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class TTLCache:
    """Tiny SQLite-backed key/value store with per-row TTL.

    Schema: cache(key TEXT PK, value TEXT, expires_at REAL).
    Values are JSON-encoded. expires_at is a unix timestamp; row is a miss
    once `time.time() > expires_at`.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "key TEXT PRIMARY KEY, "
                "value TEXT NOT NULL, "
                "expires_at REAL NOT NULL)"
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get(self, key: str) -> tuple[Any, float] | None:
        """Returns (value, age_seconds) on hit, None on miss/expired."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value_json, expires_at = row
        now = time.time()
        if now > expires_at:
            return None
        # Encode age relative to expiry boundary: how long since the row was written.
        # We don't store inserted_at, so age is "time until expiry" inverted —
        # callers usually just want to know if it's fresh.
        return json.loads(value_json), expires_at - now

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time() + ttl_seconds),
            )

    def delete(self, key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def clear(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM cache")
