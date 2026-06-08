"""Coverage for the MCP-pluggable CLI surface.

What these tests pin:
- Metro codes expand correctly (and pass through real airports unchanged).
- --json emits a stable, parseable schema.
- The compare subcommand fans out the matrix and prints one merged view.
- GoogleFlightsProvider auto-retries on transient failure.
- build_orchestrator auto-enables live Aeroplan when Browserbase creds are set.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from autopoints.cli.main import app
from autopoints.config import Settings
from autopoints.providers.base import ProviderError
from autopoints.providers.google_flights import GoogleFlightsProvider
from autopoints.search.build import (
    BuildOptions,
    _resolve_live_aeroplan,
    build_orchestrator,
)
from autopoints.search.metros import expand, is_metro, known_metros
from autopoints.search.models import Cabin


def test_expand_metro_returns_constituent_airports() -> None:
    assert expand("NYC") == ["JFK", "LGA", "EWR"]
    assert expand("nyc") == ["JFK", "LGA", "EWR"]  # case-insensitive
    assert expand("BAY") == ["SFO", "OAK", "SJC"]


def test_expand_passes_through_real_airport_codes() -> None:
    assert expand("JFK") == ["JFK"]
    assert expand("lax") == ["LAX"]


def test_is_metro_helper() -> None:
    assert is_metro("NYC")
    assert is_metro("nyc")
    assert not is_metro("JFK")
    assert not is_metro("XXX")


def test_known_metros_includes_us_and_intl_examples() -> None:
    metros = known_metros()
    assert "NYC" in metros
    assert "LON" in metros
    assert "TYO" in metros


def test_resolve_live_aeroplan_respects_explicit_flag() -> None:
    s_with = Settings(browserbase_api_key="k", browserbase_project_id="p")
    s_without = Settings(browserbase_api_key="", browserbase_project_id="")
    # Explicit True forces on regardless of env
    assert _resolve_live_aeroplan(True, s_without) is True
    # Explicit False forces off regardless of env
    assert _resolve_live_aeroplan(False, s_with) is False


def test_resolve_live_aeroplan_auto_enables_when_creds_present() -> None:
    s_with = Settings(browserbase_api_key="k", browserbase_project_id="p")
    s_without = Settings(browserbase_api_key="", browserbase_project_id="")
    # None means auto-detect
    assert _resolve_live_aeroplan(None, s_with) is True
    assert _resolve_live_aeroplan(None, s_without) is False


def test_build_orchestrator_auto_attaches_aeroplan_when_creds_present() -> None:
    s = Settings(browserbase_api_key="k", browserbase_project_id="p")
    built = build_orchestrator(BuildOptions(), settings=s)
    # AeroplanProvider should be in the award_providers list.
    provider_names = [type(p).__name__ for p in built.orchestrator.award_providers]
    assert "AeroplanProvider" in provider_names


def test_build_orchestrator_no_aeroplan_without_creds() -> None:
    s = Settings(browserbase_api_key="", browserbase_project_id="")
    built = build_orchestrator(BuildOptions(), settings=s)
    provider_names = [type(p).__name__ for p in built.orchestrator.award_providers]
    assert "AeroplanProvider" not in provider_names


def test_google_flights_provider_retries_once_on_transient_failure() -> None:
    """One fli failure should be hidden by the auto-retry, second one surfaces."""
    provider = GoogleFlightsProvider(retries=1)

    call_count = {"n": 0}

    def fake_search(*args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("transient")
        return []

    import asyncio

    with patch("autopoints.providers.google_flights._search_sync", side_effect=fake_search):
        result = asyncio.run(
            provider.search("LAX", "JFK", date(2026, 6, 13), Cabin.economy)
        )
    assert result == []
    assert call_count["n"] == 2


def test_google_flights_provider_surfaces_persistent_failure_as_provider_error() -> None:
    provider = GoogleFlightsProvider(retries=1)

    def always_fail(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("dead")

    import asyncio

    with patch("autopoints.providers.google_flights._search_sync", side_effect=always_fail):
        with pytest.raises(ProviderError, match="fli search failed"):
            asyncio.run(provider.search("LAX", "JFK", date(2026, 6, 13), Cabin.economy))


def test_cli_search_with_metro_code_fans_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity: `autopoints search LAX NYC ...` should build 3 SearchRequests
    (one for each NYC airport) and call orchestrator.run for each."""
    runner = CliRunner()
    captured_requests: list[Any] = []

    async def fake_run(self: Any, request: Any) -> Any:
        captured_requests.append(request)
        # Return a SearchOutcome with empty everything
        from autopoints.search.orchestrator import SearchOutcome

        return SearchOutcome(request=request)

    monkeypatch.setattr(
        "autopoints.search.orchestrator.Orchestrator.run", fake_run, raising=True
    )
    result = runner.invoke(app, ["search", "LAX", "NYC", "2026-06-13", "--demo"])
    assert result.exit_code == 0, result.output
    # 1 origin × 3 NYC airports = 3 SearchRequests
    assert len(captured_requests) == 3
    destinations = {r.destination for r in captured_requests}
    assert destinations == {"JFK", "LGA", "EWR"}


def test_cli_search_json_output_is_parseable_and_has_stable_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    async def fake_run(self: Any, request: Any) -> Any:
        from autopoints.search.orchestrator import SearchOutcome

        return SearchOutcome(request=request, warnings=["test-warning"])

    monkeypatch.setattr(
        "autopoints.search.orchestrator.Orchestrator.run", fake_run, raising=True
    )
    result = runner.invoke(
        app,
        ["search", "LAX", "JFK", "2026-06-13", "--demo", "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "build_warnings" in payload
    assert "outcomes" in payload
    assert len(payload["outcomes"]) == 1
    outcome = payload["outcomes"][0]
    assert outcome["request"]["origin"] == "LAX"
    assert outcome["request"]["destination"] == "JFK"
    assert outcome["request"]["depart_date"] == "2026-06-13"
    assert outcome["warnings"] == ["test-warning"]
    # The contract: these keys must always be present, even when empty.
    assert outcome["cash_offers"] == []
    assert outcome["award_offers"] == []
    assert outcome["redemptions"] == []


def test_cli_compare_fans_out_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    captured: list[Any] = []

    async def fake_run(self: Any, request: Any) -> Any:
        captured.append(request)
        from autopoints.search.orchestrator import SearchOutcome

        return SearchOutcome(request=request)

    monkeypatch.setattr(
        "autopoints.search.orchestrator.Orchestrator.run", fake_run, raising=True
    )
    # 1 origin (LAX) × 2 dests (NYC = JFK,LGA,EWR) × 2 dates = 6 combinations
    result = runner.invoke(
        app,
        [
            "compare",
            "LAX",
            "NYC",
            "2026-06-13,2026-06-14",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(captured) == 6
    combos = {(r.origin, r.destination, r.depart_date.isoformat()) for r in captured}
    assert ("LAX", "JFK", "2026-06-13") in combos
    assert ("LAX", "EWR", "2026-06-14") in combos


def test_cli_compare_rejects_malformed_date() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["compare", "LAX", "JFK", "not-a-date"])
    assert result.exit_code != 0
    assert "bad date" in result.output.lower()
