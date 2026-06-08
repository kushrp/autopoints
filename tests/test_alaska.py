"""Alaska Mileage Plan (Atmos) direct award provider — v0 skeleton tests.

Validates wiring (instantiation, BuildOptions flag, watchlist runner threading,
orchestrator error-surfacing) — not the live scraper, which is intentionally
stubbed pending the selector-discovery spike (see plan U4 Execution Note).

When U4 lands its real implementation, add:
- parse-only fixtures of live award-results HTML
- a `@pytest.mark.e2e` test that creates a Browserbase session and asserts a
  LAX-JFK redeye returns at least one AwardOffer with arrival_time populated
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from autopoints.providers.alaska import AlaskaProvider
from autopoints.providers.base import ProviderError
from autopoints.search.build import BuildOptions, build_orchestrator
from autopoints.search.models import Cabin


def test_provider_metadata() -> None:
    p = AlaskaProvider()
    assert p.name == "alaska"
    assert p.program_code == "AS"


def test_search_raises_provider_error_with_actionable_message() -> None:
    """v0 stub: search() must raise ProviderError naming the unfinished work."""
    p = AlaskaProvider()
    with pytest.raises(ProviderError) as exc:
        asyncio.run(p.search("LAX", "JFK", date(2026, 6, 14), Cabin.economy))
    # The message must point at the next step so a future implementer doesn't
    # have to grep through commits to understand why the stub raises.
    msg = str(exc.value)
    assert "alaska" in msg
    assert "selector-discovery spike" in msg


def test_per_provider_semaphore_serializes_concurrent_calls() -> None:
    """Two concurrent search() calls should not race — both raise cleanly."""
    p = AlaskaProvider()

    async def _both() -> None:
        results = await asyncio.gather(
            p.search("LAX", "JFK", date(2026, 6, 14), Cabin.economy),
            p.search("SEA", "ORD", date(2026, 6, 14), Cabin.economy),
            return_exceptions=True,
        )
        assert all(isinstance(r, ProviderError) for r in results)

    asyncio.run(_both())


def test_build_orchestrator_includes_alaska_when_flag_set() -> None:
    built = build_orchestrator(BuildOptions(demo=True, use_live_alaska=True))
    names = {p.name for p in built.orchestrator.award_providers}
    assert "alaska" in names


def test_build_orchestrator_omits_alaska_by_default() -> None:
    built = build_orchestrator(BuildOptions(demo=True))
    names = {p.name for p in built.orchestrator.award_providers}
    assert "alaska" not in names


async def test_orchestrator_surfaces_alaska_stub_as_warning(tmp_path):
    """End-to-end: orchestrator catches the stub's ProviderError into warnings
    so the user sees an actionable message rather than a stack trace."""
    from autopoints.cache.store import TTLCache
    from autopoints.search.models import SearchRequest
    from autopoints.search.orchestrator import Orchestrator

    cache = TTLCache(tmp_path / "cache.db")
    orch = Orchestrator(
        cash_providers=[],
        award_providers=[AlaskaProvider()],
        cache=cache,
    )
    req = SearchRequest(
        origin="LAX", destination="JFK",
        depart_date=date(2026, 6, 14), cabin=Cabin.economy,
    )
    out = await orch.run(req, transfer_currencies=["UR"])
    assert any("alaska" in w and "selector-discovery spike" in w for w in out.warnings)
    assert out.award_offers == []
