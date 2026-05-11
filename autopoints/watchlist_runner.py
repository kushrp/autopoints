from __future__ import annotations

import asyncio

import httpx

from autopoints.config import settings
from autopoints.search.build import BuildOptions, build_orchestrator
from autopoints.watchlists import (
    Watchlist,
    WatchlistRunResult,
    WatchlistStore,
    filter_hits,
    hit_signatures,
    webhook_payload,
)


async def run_one(
    wl: Watchlist,
    store: WatchlistStore,
    *,
    demo: bool = False,
    use_live_aeroplan: bool = False,
) -> WatchlistRunResult:
    built = build_orchestrator(BuildOptions(demo=demo, use_live_aeroplan=use_live_aeroplan))
    outcome = await built.orchestrator.run(wl.to_search_request())

    seen = store.seen_signatures(wl.id)
    hits = filter_hits(wl, outcome.best_per_program(), seen)

    store.record_seen(wl.id, hit_signatures(hits))

    return WatchlistRunResult(
        watchlist=wl,
        hits=hits,
        warnings=built.warnings + outcome.warnings,
    )


async def run_all(
    store: WatchlistStore,
    *,
    demo: bool = False,
    use_live_aeroplan: bool = False,
) -> list[WatchlistRunResult]:
    watchlists = store.list()
    if not watchlists:
        return []
    return await asyncio.gather(
        *[run_one(wl, store, demo=demo, use_live_aeroplan=use_live_aeroplan) for wl in watchlists]
    )


async def post_webhook(url: str, result: WatchlistRunResult) -> None:
    if not result.hits:
        return
    async with httpx.AsyncClient(timeout=10.0) as c:
        await c.post(url, json=webhook_payload(result))


def store_for_settings() -> WatchlistStore:
    return WatchlistStore(settings.cache_path().parent / "watchlists.db")


__all__ = ["run_one", "run_all", "post_webhook", "store_for_settings"]
