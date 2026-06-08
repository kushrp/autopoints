from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from autopoints.cli.watchlist import app as watchlist_app
from autopoints.search.build import BuildOptions, build_orchestrator
from autopoints.search.metros import expand as expand_metro
from autopoints.search.metros import is_metro
from autopoints.search.models import Cabin, SearchRequest
from autopoints.search.orchestrator import SearchOutcome

app = typer.Typer(add_completion=False, help="autopoints — cash vs. award CPP engine.")
app.add_typer(watchlist_app, name="watchlist")
console = Console()
err_console = Console(stderr=True)


@app.callback()
def _root() -> None:
    """autopoints CLI."""


def _parse_arrive_before(arrive_before: str | None) -> None:
    if arrive_before is None:
        return
    from autopoints.search.orchestrator import (
        ArriveBeforeParseError,
        parse_arrive_before,
    )

    try:
        parse_arrive_before(arrive_before)
    except ArriveBeforeParseError as e:
        raise typer.BadParameter(str(e)) from e


def _parse_dates(spec: str) -> list[date]:
    """Accept either a single YYYY-MM-DD or a comma-separated list."""
    out: list[date] = []
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(date.fromisoformat(raw))
        except ValueError as e:
            raise typer.BadParameter(f"bad date '{raw}': {e}") from e
    if not out:
        raise typer.BadParameter("at least one date is required")
    return out


@app.command()
def search(
    origin: Annotated[str, typer.Argument(help="Origin IATA or metro (e.g. JFK, NYC, BAY)")],
    destination: Annotated[
        str, typer.Argument(help="Destination IATA or metro (e.g. JFK, NYC, BAY)")
    ],
    depart: Annotated[str, typer.Argument(help="Departure date, YYYY-MM-DD")],
    window: Annotated[int, typer.Option(help="± N days around departure")] = 0,
    cabin: Annotated[Cabin, typer.Option(help="Cabin class")] = Cabin.economy,
    passengers: Annotated[int, typer.Option(help="Number of adult passengers")] = 1,
    refresh: Annotated[bool, typer.Option("--refresh", help="Bypass cache")] = False,
    demo: Annotated[
        bool,
        typer.Option("--demo", help="Use synthetic cash data (no live providers called)."),
    ] = False,
    use_live_aeroplan: Annotated[
        bool | None,
        typer.Option(
            "--live-aeroplan/--no-live-aeroplan",
            help="Hit Aeroplan's live award-search endpoint. Auto-enabled when "
            "BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID are configured (the "
            "v1.c-2 Kasada-bypass path). Explicit flag overrides auto-detect.",
        ),
    ] = None,
    use_live_alaska: Annotated[
        bool,
        typer.Option(
            "--live-alaska/--no-live-alaska",
            help="Include Alaska Mileage Plan (Atmos) live award search. "
            "Requires BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID in .env.",
        ),
    ] = False,
    arrive_before: Annotated[
        str | None,
        typer.Option(
            "--arrive-before",
            help="Filter to flights arriving before HH:MM<TZ>, e.g. '08:00ET'. "
            "Accepted TZs: ET, CT, MT, PT, AKT, HT. Applied post-rank against "
            "live results; chart-floor results (no time data) always pass.",
        ),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a stable JSON document on stdout instead of the rich "
            "table. Schema mirrors SearchOutcome — MCP-consumable.",
        ),
    ] = False,
) -> None:
    """Search a route and print a CPP-ranked redemption table.

    Metro codes (NYC, LON, BAY, …) expand to their constituent airports and
    the route fans out to every (origin × destination) pair. The output is
    one merged table sorted by effective CPP.
    """
    _parse_arrive_before(arrive_before)
    origins = expand_metro(origin)
    destinations = expand_metro(destination)
    depart_dt = date.fromisoformat(depart)

    requests = [
        SearchRequest(
            origin=o,
            destination=d,
            depart_date=depart_dt,
            window_days=window,
            cabin=cabin,
            passengers=passengers,
            arrive_before_local=arrive_before,
        )
        for o in origins
        for d in destinations
    ]

    built = build_orchestrator(
        BuildOptions(
            demo=demo,
            use_live_aeroplan=use_live_aeroplan,
            use_live_alaska=use_live_alaska,
            force_refresh=refresh,
        )
    )
    if not output_json:
        for w in built.warnings:
            err_console.print(f"[yellow]warning:[/yellow] {w}")

    outcomes = asyncio.run(_run_requests(built.orchestrator, requests))

    if output_json:
        _render_json(outcomes, build_warnings=built.warnings)
    else:
        _render_outcomes(outcomes, is_metro_search=(is_metro(origin) or is_metro(destination)))


@app.command()
def compare(
    origins: Annotated[
        str,
        typer.Argument(
            help="Comma-separated origins (IATA or metro). e.g. LAX or LAX,SFO or BAY",
        ),
    ],
    destinations: Annotated[
        str,
        typer.Argument(
            help="Comma-separated destinations (IATA or metro). e.g. NYC or JFK,LGA",
        ),
    ],
    depart: Annotated[
        str, typer.Argument(help="Comma-separated dates (YYYY-MM-DD). e.g. 2026-06-13,2026-06-14")
    ],
    cabin: Annotated[Cabin, typer.Option(help="Cabin class")] = Cabin.economy,
    passengers: Annotated[int, typer.Option(help="Number of adult passengers")] = 1,
    refresh: Annotated[bool, typer.Option("--refresh", help="Bypass cache")] = False,
    arrive_before: Annotated[
        str | None,
        typer.Option(
            "--arrive-before",
            help="Filter to flights arriving before HH:MM<TZ>, e.g. '08:00ET'.",
        ),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of the rich table."),
    ] = False,
) -> None:
    """Cross-compare multiple origins × destinations × dates.

    Designed for "find me the cheapest LAX-area to NYC flight this weekend" —
    fans out the search matrix, runs everything in parallel through the
    orchestrator, then prints one unified table sorted by effective CPP.
    """
    _parse_arrive_before(arrive_before)

    origin_codes: list[str] = []
    for raw in origins.split(","):
        origin_codes.extend(expand_metro(raw.strip()))
    dest_codes: list[str] = []
    for raw in destinations.split(","):
        dest_codes.extend(expand_metro(raw.strip()))
    depart_dates = _parse_dates(depart)

    requests = [
        SearchRequest(
            origin=o,
            destination=d,
            depart_date=dt,
            cabin=cabin,
            passengers=passengers,
            arrive_before_local=arrive_before,
        )
        for o in origin_codes
        for d in dest_codes
        for dt in depart_dates
    ]
    if not output_json:
        err_console.print(
            f"[dim]running {len(requests)} searches "
            f"({len(origin_codes)} origins × {len(dest_codes)} dests × {len(depart_dates)} dates)[/dim]"
        )

    built = build_orchestrator(BuildOptions(force_refresh=refresh))
    if not output_json:
        for w in built.warnings:
            err_console.print(f"[yellow]warning:[/yellow] {w}")

    outcomes = asyncio.run(_run_requests(built.orchestrator, requests))

    if output_json:
        _render_json(outcomes, build_warnings=built.warnings)
    else:
        _render_outcomes(outcomes, is_metro_search=True)


async def _run_requests(orch: object, requests: list[SearchRequest]) -> list[SearchOutcome]:
    """Run multiple SearchRequests concurrently through one orchestrator. The
    orchestrator already gathers cash+award providers internally, so the
    speedup here is across (origin, destination, date) combinations.
    """
    # The orchestrator is shared; its cache and providers are fine to use
    # concurrently because everything underneath is async and stateless.
    tasks = [orch.run(r) for r in requests]  # type: ignore[attr-defined]
    return await asyncio.gather(*tasks)


def _render_outcomes(outcomes: list[SearchOutcome], is_metro_search: bool) -> None:
    if len(outcomes) == 1 and not is_metro_search:
        _render_single(outcomes[0])
        return

    console.print(
        f"\n[bold]Cross-comparison across {len(outcomes)} route × date combinations[/bold]"
    )

    cash_rows: list[tuple[str, str, str, int, str | None, int, int]] = []
    for o in outcomes:
        for offer in o.cash_offers:
            cash_rows.append(
                (
                    o.request.origin,
                    o.request.destination,
                    offer.depart_date.isoformat(),
                    offer.cash_cents,
                    offer.carrier,
                    offer.stops,
                    offer.duration_minutes or 0,
                )
            )
    cash_rows.sort(key=lambda r: r[3])

    if cash_rows:
        cash_table = Table(title="Cheapest cash options", show_lines=False)
        cash_table.add_column("From", justify="center")
        cash_table.add_column("To", justify="center")
        cash_table.add_column("Date")
        cash_table.add_column("Carrier", justify="center")
        cash_table.add_column("Stops", justify="center")
        cash_table.add_column("Duration", justify="right")
        cash_table.add_column("Cash", justify="right")
        for row in cash_rows[:10]:
            origin, dest, d, cents, carrier, stops, dur = row
            stops_label = "nonstop" if stops == 0 else f"{stops}-stop"
            cash_table.add_row(
                origin,
                dest,
                d,
                carrier or "??",
                stops_label,
                f"{dur // 60}h{dur % 60:02d}",
                f"${cents / 100:.0f}",
            )
        console.print(cash_table)

    redemptions: list[tuple[SearchOutcome, object]] = []
    for o in outcomes:
        for r in o.best_per_program():
            redemptions.append((o, r))
    redemptions.sort(key=lambda pair: pair[1].effective_cpp, reverse=True)  # type: ignore[attr-defined]

    if redemptions:
        table = Table(title="Top redemptions by effective CPP", show_lines=False)
        table.add_column("From", justify="center")
        table.add_column("To", justify="center")
        table.add_column("Date")
        table.add_column("Transfer", justify="center")
        table.add_column("Program", justify="center")
        table.add_column("Points", justify="right")
        table.add_column("Taxes", justify="right")
        table.add_column("Cash", justify="right")
        table.add_column("Eff. CPP", justify="right")
        table.add_column("Verdict", justify="center")
        verdict_style = {"great": "bold green", "good": "green", "ok": "yellow", "bad": "red"}
        for outcome, r in redemptions[:10]:
            req = outcome.request
            table.add_row(
                req.origin,
                req.destination,
                r.award_offer.depart_date.isoformat(),  # type: ignore[attr-defined]
                r.transfer_program,  # type: ignore[attr-defined]
                r.points_program,  # type: ignore[attr-defined]
                f"{r.effective_points_required:,}",  # type: ignore[attr-defined]
                f"${r.award_offer.taxes_cents / 100:.2f}",  # type: ignore[attr-defined]
                f"${r.cash_offer.cash_cents / 100:.0f}",  # type: ignore[attr-defined]
                f"{r.effective_cpp:.2f}¢",  # type: ignore[attr-defined]
                f"[{verdict_style[r.verdict]}]{r.verdict}[/{verdict_style[r.verdict]}]",  # type: ignore[attr-defined]
            )
        console.print(table)

    # Aggregate warnings from every outcome, dedupe to avoid spam.
    seen_warnings: set[str] = set()
    for o in outcomes:
        for w in o.warnings:
            if w not in seen_warnings:
                err_console.print(f"[yellow]warning:[/yellow] {w}")
                seen_warnings.add(w)


def _render_single(outcome: SearchOutcome) -> None:
    req = outcome.request
    console.print(
        f"\n[bold]{req.origin} → {req.destination}[/bold]  "
        f"{req.depart_date.isoformat()}"
        f"{f' ±{req.window_days}d' if req.window_days else ''}  "
        f"cabin={req.cabin.value}  pax={req.passengers}"
    )

    if outcome.cash_offers:
        cheapest_by_date: dict[str, int] = {}
        for o in outcome.cash_offers:
            d = o.depart_date.isoformat()
            if d not in cheapest_by_date or o.cash_cents < cheapest_by_date[d]:
                cheapest_by_date[d] = o.cash_cents
        cash_summary = "  ".join(
            f"{d} ${c / 100:.2f}" for d, c in sorted(cheapest_by_date.items())
        )
        console.print(f"[dim]cheapest cash:[/dim] {cash_summary}")
    else:
        console.print("[dim]cheapest cash:[/dim] (none)")

    table = Table(title="Redemptions ranked by effective CPP", show_lines=False)
    table.add_column("Transfer", justify="center")
    table.add_column("Program", justify="center")
    table.add_column("Date")
    table.add_column("Carrier", justify="center")
    table.add_column("Points", justify="right")
    table.add_column("Eff. Points", justify="right")
    table.add_column("Taxes", justify="right")
    table.add_column("Cash", justify="right")
    table.add_column("CPP", justify="right")
    table.add_column("Eff. CPP", justify="right")
    table.add_column("Verdict", justify="center")
    table.add_column("Notes")

    verdict_style = {"great": "bold green", "good": "green", "ok": "yellow", "bad": "red"}

    for r in outcome.best_per_program():
        table.add_row(
            r.transfer_program,
            r.points_program,
            r.award_offer.depart_date.isoformat(),
            r.award_offer.operating_carrier,
            f"{r.points_required:,}",
            f"{r.effective_points_required:,}",
            f"${r.award_offer.taxes_cents / 100:.2f}",
            f"${r.cash_offer.cash_cents / 100:.2f}",
            f"{r.cpp:.2f}¢",
            f"{r.effective_cpp:.2f}¢",
            f"[{verdict_style[r.verdict]}]{r.verdict}[/{verdict_style[r.verdict]}]",
            "; ".join(r.notes),
        )

    console.print(table)

    for w in outcome.warnings:
        err_console.print(f"[yellow]warning:[/yellow] {w}")


def _render_json(outcomes: list[SearchOutcome], build_warnings: list[str]) -> None:
    """Stable JSON contract for MCP and programmatic callers.

    Shape:
      {
        "build_warnings": [str],
        "outcomes": [
          {
            "request": SearchRequest,
            "cash_offers": [FlightOffer],
            "award_offers": [AwardOffer],
            "redemptions": [RedemptionResult],  # sorted by effective_cpp desc
            "warnings": [str]
          }
        ]
      }

    All nested objects are pydantic .model_dump(mode="json") — dates as ISO
    strings, enums as their values.
    """
    payload = {
        "build_warnings": list(build_warnings),
        "outcomes": [
            {
                "request": o.request.model_dump(mode="json"),
                "cash_offers": [c.model_dump(mode="json") for c in o.cash_offers],
                "award_offers": [a.model_dump(mode="json") for a in o.award_offers],
                "redemptions": [
                    r.model_dump(mode="json") for r in o.best_per_program()
                ],
                "warnings": list(o.warnings),
            }
            for o in outcomes
        ],
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    app()
