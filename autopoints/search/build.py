"""Wire up an Orchestrator with the providers appropriate for the current
config + flags. Single source of truth shared by the CLI and the HTTP layer."""

from __future__ import annotations

from dataclasses import dataclass

from autopoints.cache.store import TTLCache
from autopoints.config import Settings, settings as default_settings
from autopoints.providers.aeroplan import AeroplanProvider
from autopoints.providers.base import AwardProvider, CashProvider, ProviderError
from autopoints.providers.demo import DemoCashProvider
from autopoints.providers.google_flights import GoogleFlightsProvider
from autopoints.providers.static_charts import StaticChartProvider
from autopoints.search.orchestrator import Orchestrator

# Programs we have static charts for. Each adds an AwardProvider.
SUPPORTED_CHART_PROGRAMS: tuple[str, ...] = ("AC", "BA", "VS")


@dataclass
class BuildOptions:
    demo: bool = False
    use_live_aeroplan: bool = False
    force_refresh: bool = False


@dataclass
class BuildResult:
    orchestrator: Orchestrator
    warnings: list[str]


def build_orchestrator(opts: BuildOptions, settings: Settings = default_settings) -> BuildResult:
    warnings: list[str] = []

    cash_providers: list[CashProvider] = []
    if opts.demo:
        cash_providers.append(DemoCashProvider())
    else:
        # Google Flights via fli replaces Amadeus (decommissioned 2026-07-17).
        # No API key required. The provider raises ProviderError on upstream
        # failure; the orchestrator surfaces it as a warning.
        cash_providers.append(GoogleFlightsProvider())

    award_providers: list[AwardProvider] = []
    if opts.use_live_aeroplan:
        award_providers.append(AeroplanProvider())
    for code in SUPPORTED_CHART_PROGRAMS:
        try:
            award_providers.append(StaticChartProvider(code))
        except ProviderError as e:
            warnings.append(str(e))

    orch = Orchestrator(
        cash_providers=cash_providers,
        award_providers=award_providers,
        cache=TTLCache(settings.cache_path()),
        cpp_great=settings.autopoints_cpp_great,
        cpp_good=settings.autopoints_cpp_good,
        force_refresh=opts.force_refresh,
    )
    return BuildResult(orchestrator=orch, warnings=warnings)
