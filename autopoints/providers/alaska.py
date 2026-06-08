"""Alaska Mileage Plan (Atmos Rewards) direct award provider.

**STATUS: v0 skeleton — search() is intentionally stubbed.** The selector-
discovery spike required by the plan's U4 Execution Note has not run yet;
encoding form-driving + result-parsing logic without live element refs would
ship a brittle scraper that breaks on first contact. The full wiring is in
place (Settings, CLI flag, build registration, watchlist runner threading),
so a follow-up commit can add the search() body without touching anything
else in the v0 PR.

Phase-2 work:
1. Run scripts/spike_alaska.py (not yet committed) against a live Browserbase
   session to map: search-form Web Component selectors, result-row data-testid
   attributes, partner-award-row vs. own-metal-row structure, next-day arrival
   ("+1") rendering.
2. Encode the discovered selectors into _parse_results and the form-driving
   sequence into search().
3. Add fixture HTML to tests/test_alaska.py + parse-only assertions.
4. Mark live calls @pytest.mark.e2e.

Origin: docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md U4
Plan: docs/plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md U4
"""

from __future__ import annotations

import asyncio
from datetime import date

from autopoints.providers.base import AwardProvider, ProviderError
from autopoints.search.models import AwardOffer, Cabin


class AlaskaProvider(AwardProvider):
    name = "alaska"
    program_code = "AS"

    def __init__(self) -> None:
        # Per-provider semaphore. Orchestrator fan-out (providers × date_window)
        # would otherwise create simultaneous Browserbase sessions; this caps
        # the provider's own concurrency to one search at a time. A global
        # Browserbase semaphore is a phase-2 follow-up.
        self._search_semaphore = asyncio.Semaphore(1)

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[AwardOffer]:
        async with self._search_semaphore:
            raise ProviderError(
                "alaska: provider skeleton — selector-discovery spike pending. "
                "See plan U4 Execution Note in "
                "docs/plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md "
                "— selector discovery is a one-off interactive task; reference "
                "script is intentionally not committed."
            )
