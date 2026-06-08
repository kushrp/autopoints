"""Discord bot — your personal travel agent.

Slash commands:
  /search       Run a one-off search and show top redemptions.
  /watchlist add | list | remove | run

Background loop (optional): re-runs all watchlists on a configurable interval
and posts NEW hits to a designated channel.

This module imports discord only inside `make_bot()` so the rest of the
package stays importable without the optional dep installed.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING

from autopoints.discord_bot.embeds import (
    search_results_embed,
    watchlist_list_embed,
    watchlist_run_embed,
)
from autopoints.search.build import BuildOptions, build_orchestrator
from autopoints.search.models import Cabin, SearchRequest
from autopoints.watchlist_runner import run_all, store_for_settings

if TYPE_CHECKING:
    import discord  # noqa: F401


def make_bot(
    *,
    guild_id: int | None = None,
    notify_channel_id: int | None = None,
    run_interval_minutes: int | None = None,
    demo_mode: bool = False,
):
    """Build the discord.Client + command tree."""
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    guild = discord.Object(id=guild_id) if guild_id else None

    cabin_choices = [
        app_commands.Choice(name=c.value, value=c.value) for c in Cabin
    ]

    @client.event
    async def on_ready() -> None:
        if guild:
            await tree.sync(guild=guild)
        else:
            await tree.sync()
        print(f"autopoints discord bot ready as {client.user}")
        if run_interval_minutes and notify_channel_id:
            asyncio.create_task(_watchlist_loop(client, notify_channel_id, run_interval_minutes, demo_mode))

    @tree.command(name="search", description="Search cash vs. points for a route.", guild=guild)
    @app_commands.choices(cabin=cabin_choices)
    async def search_cmd(
        interaction: discord.Interaction,
        origin: str,
        destination: str,
        depart_date_iso: str,
        window: int = 0,
        cabin: str = "economy",
        passengers: int = 1,
        demo: bool = False,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            req = SearchRequest(
                origin=origin.upper(),
                destination=destination.upper(),
                depart_date=date.fromisoformat(depart_date_iso),
                window_days=max(0, min(window, 7)),
                cabin=Cabin(cabin),
                passengers=max(1, min(passengers, 9)),
            )
        except ValueError as e:
            await interaction.followup.send(f"bad input: {e}")
            return

        built = build_orchestrator(BuildOptions(demo=demo or demo_mode))
        outcome = await built.orchestrator.run(req)
        embed = search_results_embed(
            origin=req.origin,
            destination=req.destination,
            depart_date=req.depart_date.isoformat(),
            window_days=req.window_days,
            cabin=req.cabin.value,
            redemptions=outcome.best_per_program(),
            warnings=built.warnings + outcome.warnings,
        )
        await interaction.followup.send(embed=discord.Embed.from_dict(embed))

    watchlist_group = app_commands.Group(name="watchlist", description="Saved searches.", guild_ids=[guild_id] if guild_id else None)

    @watchlist_group.command(name="add", description="Save a watchlist.")
    @app_commands.choices(cabin=cabin_choices)
    async def wl_add(
        interaction: discord.Interaction,
        origin: str,
        destination: str,
        depart_date_iso: str,
        window: int = 3,
        cabin: str = "economy",
        threshold: float = 1.8,
        passengers: int = 1,
        label: str | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        store = store_for_settings()
        wl = store.add(
            origin=origin, destination=destination,
            depart_date=date.fromisoformat(depart_date_iso),
            window_days=max(0, min(window, 7)),
            cabin=Cabin(cabin), passengers=max(1, min(passengers, 9)),
            threshold_cpp=max(0.0, min(threshold, 10.0)),
            label=label,
        )
        await interaction.followup.send(
            f"added watchlist `{wl.id}`: {wl.origin}→{wl.destination} "
            f"{wl.depart_date} ±{wl.window_days}d threshold={wl.threshold_cpp:.2f}¢"
        )

    @watchlist_group.command(name="list", description="List saved watchlists.")
    async def wl_list(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        embed = watchlist_list_embed(store_for_settings().list())
        await interaction.followup.send(embed=discord.Embed.from_dict(embed))

    @watchlist_group.command(name="remove", description="Delete a watchlist by id.")
    async def wl_remove(interaction: discord.Interaction, id: str) -> None:
        await interaction.response.defer(thinking=True)
        if store_for_settings().remove(id):
            await interaction.followup.send(f"removed `{id}`")
        else:
            await interaction.followup.send(f"no watchlist with id `{id}`")

    @watchlist_group.command(name="run", description="Run all saved watchlists.")
    async def wl_run(interaction: discord.Interaction, only_new: bool = False, demo: bool = False) -> None:
        await interaction.response.defer(thinking=True)
        results = await run_all(store_for_settings(), demo=demo or demo_mode)
        if not results:
            await interaction.followup.send("no watchlists configured. use `/watchlist add` first.")
            return
        embeds = [
            discord.Embed.from_dict(
                watchlist_run_embed(r.watchlist, r.hits, only_new=only_new, warnings=r.warnings)
            )
            for r in results
        ]
        # Discord allows up to 10 embeds per message
        await interaction.followup.send(embeds=embeds[:10])

    tree.add_command(watchlist_group)
    return client


async def _watchlist_loop(
    client,
    channel_id: int,
    interval_minutes: int,
    demo_mode: bool,
) -> None:
    """Background task: re-run all watchlists every N minutes; post NEW hits."""
    import discord
    await client.wait_until_ready()
    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    while not client.is_closed():
        try:
            results = await run_all(store_for_settings(), demo=demo_mode)
            for r in results:
                new_hits = [h for h in r.hits if h.is_new]
                # Surface warnings even when no new hits — otherwise a failing
                # watchlist running unattended in the background is invisible
                # to the user. r.warnings carries U2's degraded-result text
                # and U3's "filter disabled" text.
                if not new_hits and not r.warnings:
                    continue
                embed = watchlist_run_embed(
                    r.watchlist, new_hits, only_new=True, warnings=r.warnings
                )
                await channel.send(embed=discord.Embed.from_dict(embed))
        except Exception as e:  # noqa: BLE001 — bot must keep running
            print(f"watchlist loop error: {e}")
        await asyncio.sleep(interval_minutes * 60)
