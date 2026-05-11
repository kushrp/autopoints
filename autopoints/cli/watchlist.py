from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from autopoints.search.models import Cabin
from autopoints.watchlist_runner import post_webhook, run_all, store_for_settings
from autopoints.watchlists import format_hit_text

app = typer.Typer(help="Saved searches with auto-diff against previous runs.")
console = Console()


@app.command("add")
def add(
    origin: Annotated[str, typer.Argument(help="Origin IATA code")],
    destination: Annotated[str, typer.Argument(help="Destination IATA code")],
    depart: Annotated[str, typer.Argument(help="Departure date YYYY-MM-DD")],
    window: Annotated[int, typer.Option(help="± N days around departure")] = 3,
    cabin: Annotated[Cabin, typer.Option(help="Cabin class")] = Cabin.economy,
    passengers: Annotated[int, typer.Option(help="Adult passengers")] = 1,
    threshold: Annotated[float, typer.Option(help="Min effective CPP to flag")] = 1.8,
    label: Annotated[str | None, typer.Option(help="Friendly name for this search")] = None,
) -> None:
    """Add a saved search."""
    store = store_for_settings()
    wl = store.add(
        origin=origin,
        destination=destination,
        depart_date=date.fromisoformat(depart),
        window_days=window,
        cabin=cabin,
        passengers=passengers,
        threshold_cpp=threshold,
        label=label,
    )
    console.print(
        f"added watchlist [bold]{wl.id}[/bold]: "
        f"{wl.origin}→{wl.destination} {wl.depart_date} ±{wl.window_days}d "
        f"{wl.cabin.value} threshold={wl.threshold_cpp}cpp"
    )


@app.command("list")
def list_() -> None:
    """List saved searches."""
    store = store_for_settings()
    watchlists = store.list()
    if not watchlists:
        console.print("[dim]no watchlists. add one with `autopoints watchlist add`[/dim]")
        return

    t = Table(title="Watchlists")
    t.add_column("ID")
    t.add_column("Label")
    t.add_column("Route")
    t.add_column("Date ±")
    t.add_column("Cabin")
    t.add_column("Pax", justify="right")
    t.add_column("Threshold", justify="right")
    for wl in watchlists:
        t.add_row(
            wl.id,
            wl.label or "—",
            f"{wl.origin}→{wl.destination}",
            f"{wl.depart_date} ±{wl.window_days}d",
            wl.cabin.value,
            str(wl.passengers),
            f"{wl.threshold_cpp:.2f}cpp",
        )
    console.print(t)


@app.command("remove")
def remove(id_: Annotated[str, typer.Argument(help="Watchlist ID to delete")]) -> None:
    """Remove a saved search."""
    store = store_for_settings()
    if store.remove(id_):
        console.print(f"removed [bold]{id_}[/bold]")
    else:
        console.print(f"[red]no watchlist with id {id_}[/red]")
        raise typer.Exit(code=1)


@app.command("run")
def run(
    demo: Annotated[bool, typer.Option("--demo", help="Use synthetic cash data")] = False,
    use_live_aeroplan: Annotated[
        bool,
        typer.Option(
            "--live-aeroplan/--no-live-aeroplan",
            help="Hit Aeroplan's live award-search endpoint",
        ),
    ] = False,
    webhook: Annotated[
        str | None,
        typer.Option("--webhook", help="POST hits as JSON to this URL"),
    ] = None,
    only_new: Annotated[
        bool,
        typer.Option("--only-new", help="Only print/post NEW hits (vs. previously-seen)"),
    ] = False,
) -> None:
    """Run all saved searches; print and (optionally) webhook new + ongoing hits."""
    store = store_for_settings()
    results = asyncio.run(run_all(store, demo=demo, use_live_aeroplan=use_live_aeroplan))

    if not results:
        console.print("[dim]no watchlists configured[/dim]")
        return

    total_new = 0
    total_hits = 0
    for r in results:
        for w in r.warnings:
            console.print(f"[yellow]warning:[/yellow] [{r.watchlist.id}] {w}")
        for hit in r.hits:
            if only_new and not hit.is_new:
                continue
            total_hits += 1
            if hit.is_new:
                total_new += 1
            style = "bold green" if hit.is_new else "dim"
            console.print(f"[{style}]{format_hit_text(hit, r.watchlist)}[/{style}]")

    console.print(
        f"\n[bold]{total_new} new[/bold] / {total_hits} total hits across {len(results)} watchlists"
    )

    if webhook:
        async def _post_all() -> None:
            for r in results:
                if only_new:
                    r.hits = [h for h in r.hits if h.is_new]
                if r.hits:
                    await post_webhook(webhook, r)
        asyncio.run(_post_all())
        console.print(f"[dim]posted to webhook: {webhook}[/dim]")
