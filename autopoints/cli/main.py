from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from autopoints.search.build import BuildOptions, build_orchestrator
from autopoints.search.models import Cabin, SearchRequest
from autopoints.search.orchestrator import SearchOutcome

app = typer.Typer(add_completion=False, help="autopoints — cash vs. award CPP engine.")
console = Console()


@app.callback()
def _root() -> None:
    """autopoints CLI."""


@app.command()
def search(
    origin: Annotated[str, typer.Argument(help="Origin IATA code, e.g. JFK")],
    destination: Annotated[str, typer.Argument(help="Destination IATA code, e.g. PHX")],
    depart: Annotated[str, typer.Argument(help="Departure date, YYYY-MM-DD")],
    window: Annotated[int, typer.Option(help="± N days around departure")] = 0,
    cabin: Annotated[Cabin, typer.Option(help="Cabin class")] = Cabin.economy,
    passengers: Annotated[int, typer.Option(help="Number of adult passengers")] = 1,
    refresh: Annotated[bool, typer.Option("--refresh", help="Bypass cache")] = False,
    demo: Annotated[
        bool,
        typer.Option("--demo", help="Use synthetic cash data (no Amadeus key needed)."),
    ] = False,
    use_live_aeroplan: Annotated[
        bool,
        typer.Option(
            "--live-aeroplan/--no-live-aeroplan",
            help="Hit Aeroplan's live award-search endpoint (may be bot-blocked).",
        ),
    ] = False,
) -> None:
    """Search a route and print a CPP-ranked redemption table."""
    request = SearchRequest(
        origin=origin,
        destination=destination,
        depart_date=date.fromisoformat(depart),
        window_days=window,
        cabin=cabin,
        passengers=passengers,
    )

    built = build_orchestrator(
        BuildOptions(demo=demo, use_live_aeroplan=use_live_aeroplan, force_refresh=refresh)
    )
    for w in built.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")

    outcome = asyncio.run(built.orchestrator.run(request))
    _render(outcome)


def _render(outcome: SearchOutcome) -> None:
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
        console.print(f"[yellow]warning:[/yellow] {w}")


if __name__ == "__main__":
    app()
