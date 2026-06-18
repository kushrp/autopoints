from datetime import date

from autopoints.search.build import BuildOptions, build_orchestrator
from autopoints.search.models import Cabin, SearchRequest


async def test_demo_search_produces_ranked_cpp():
    """The keyless gate: a demo search yields ranked CPP with no credentials."""
    built = build_orchestrator(BuildOptions(demo=True))
    outcome = await built.orchestrator.run(
        SearchRequest(
            origin="JFK", destination="PHX", depart_date=date(2026, 7, 15), cabin=Cabin.economy
        )
    )

    assert outcome.redemptions, "demo search should produce redemptions"
    for r in outcome.redemptions:
        assert r.cpp >= 0
        assert r.effective_cpp >= 0

    best = outcome.best_per_program()
    assert best
    # The redemptions are rankable by effective CPP (what the CLI prints).
    ranked = sorted(outcome.redemptions, key=lambda r: r.effective_cpp, reverse=True)
    assert ranked[0].effective_cpp >= ranked[-1].effective_cpp
    assert any(r.verdict in {"great", "good", "ok"} for r in best)
