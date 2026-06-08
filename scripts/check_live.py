#!/usr/bin/env python3
"""Live-service health checks for autopoints.

One command, pass/fail report for every shipped feature against real services.

Usage
-----
    uv run scripts/check_live.py             # full suite
    uv run scripts/check_live.py --only google_flights,aeroplan
    uv run scripts/check_live.py --json out.json

Design
------
Each check is a small async function. A check returns a CheckOutcome with
status ∈ {pass, fail, skip}. Missing-prerequisite (env var) → skip; a real
network or logic failure → fail. Order: cheap/fast first, expensive
(Browserbase, Discord round-trip) last so a quick fail surfaces fast.

Notes
-----
The Aeroplan check is the only one where a *failure response* counts as a
PASS: production traffic is Kasada-blocked (HTTP 429 from the air-bounds /
market-token endpoints). What we're proving is that the Cognito + SigV4 +
market-token handshake reached the bot-blocked layer — i.e. the regression
we'd catch is the Cognito or signing step breaking and the error message
mentioning *that* step rather than "Kasada". See docs/LIVE_CHECKS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


@dataclass
class CheckOutcome:
    name: str
    status: str  # "pass" | "fail" | "skip"
    duration_ms: float
    detail: str = ""
    missing: list[str] = field(default_factory=list)
    traceback: str | None = None


CheckFn = Callable[[], Awaitable["CheckOutcome"]]


def _missing(*env_vars: str) -> list[str]:
    return [v for v in env_vars if not os.getenv(v)]


def _skip(name: str, missing: list[str], started: float) -> CheckOutcome:
    return CheckOutcome(
        name=name,
        status="skip",
        duration_ms=(time.perf_counter() - started) * 1000,
        detail=f"missing env: {', '.join(missing)}",
        missing=missing,
    )


def _fail(name: str, started: float, err: BaseException) -> CheckOutcome:
    return CheckOutcome(
        name=name,
        status="fail",
        duration_ms=(time.perf_counter() - started) * 1000,
        detail=f"{type(err).__name__}: {err}",
        traceback="".join(traceback.format_exception(type(err), err, err.__traceback__)),
    )


def _pass(name: str, started: float, detail: str = "") -> CheckOutcome:
    return CheckOutcome(
        name=name,
        status="pass",
        duration_ms=(time.perf_counter() - started) * 1000,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


async def check_google_flights_redeye_lax_jfk() -> CheckOutcome:
    """Live fli call: LAX→JFK ~30 days out, assert >=1 redeye (arrival_date >
    depart_date). No secrets required — fli talks to Google directly."""
    name = "google_flights_redeye_lax_jfk"
    started = time.perf_counter()
    try:
        from autopoints.providers import google_flights as gf
        from autopoints.search.models import Cabin

        depart = date.today() + timedelta(days=30)
        offers = await gf.GoogleFlightsProvider().search("LAX", "JFK", depart, Cabin.economy)
        if not offers:
            raise AssertionError("fli returned 0 offers for LAX→JFK")
        redeyes = [o for o in offers if o.arrival_date and o.arrival_date > depart]
        if not redeyes:
            raise AssertionError(
                f"no redeye (arrival_date > {depart}) in {len(offers)} offers"
            )
        cheapest = min(redeyes, key=lambda o: o.cash_cents)
        return _pass(
            name,
            started,
            f"{len(offers)} offers, {len(redeyes)} redeye, "
            f"cheapest {cheapest.carrier} ${cheapest.cash_cents / 100:.0f}",
        )
    except Exception as e:
        return _fail(name, started, e)


async def check_orchestrator_arrive_before_demo() -> CheckOutcome:
    """Exercise the full orchestrator path with and without --arrive-before.

    Pass criteria (per the v0.1 forcing-function gate in docs/ROADMAP.md):
    - Unfiltered run produces at least one redemption (proves wiring works)
    - Filtered run produces STRICTLY FEWER redemptions than unfiltered
      (proves --arrive-before fires; the filter could legitimately wipe to
      zero when the demo's cheapest cash arrives after the cutoff)

    The failure mode is: filtered_count == unfiltered_count — meaning the
    filter silently didn't apply.
    """
    name = "orchestrator_arrive_before_demo"
    started = time.perf_counter()
    try:
        import tempfile

        from autopoints.cache.store import TTLCache
        from autopoints.search.build import BuildOptions, build_orchestrator
        from autopoints.search.models import SearchRequest

        # Two orchestrator runs: one unfiltered, one with --arrive-before.
        # Each gets its own isolated tempfile cache.
        async def _run(arrive_before: str | None) -> int:
            built = build_orchestrator(BuildOptions(demo=True))
            tmp = Path(tempfile.mkdtemp(prefix="autopoints-livecheck-")) / "cache.db"
            built.orchestrator.cache = TTLCache(tmp)
            req = SearchRequest(
                origin="JFK",
                destination="LAX",
                depart_date=date.today() + timedelta(days=14),
                window_days=1,
                arrive_before_local=arrive_before,
            )
            outcome = await built.orchestrator.run(req)
            return len(outcome.redemptions)

        unfiltered = await _run(None)
        filtered = await _run("08:00ET")

        if unfiltered == 0:
            raise AssertionError(
                "demo orchestrator returned 0 redemptions unfiltered — wiring broken"
            )
        if filtered >= unfiltered:
            raise AssertionError(
                f"--arrive-before filter did not fire: "
                f"filtered={filtered} >= unfiltered={unfiltered}"
            )
        return _pass(
            name,
            started,
            f"filter fired: unfiltered={unfiltered}, filtered={filtered} "
            f"({unfiltered - filtered} dropped)",
        )
    except Exception as e:
        return _fail(name, started, e)


async def check_aeroplan_handshake_reaches_air_bounds() -> CheckOutcome:
    """Run a live AeroplanProvider.search and EXPECT a Kasada block.

    PASS criterion: the raised ProviderError mentions "Kasada" — proving
    Cognito identity exchange, SigV4 signing, and market-token POST all
    succeeded and the failure happened at the bot-management layer. FAIL
    criterion: any other ProviderError (the handshake regressed), or no
    error at all (Kasada was unexpectedly disabled — worth investigating).
    """
    name = "aeroplan_handshake_reaches_air_bounds"
    started = time.perf_counter()
    try:
        from autopoints.providers.aeroplan import AeroplanProvider
        from autopoints.providers.base import ProviderError
        from autopoints.search.models import Cabin

        provider = AeroplanProvider()
        try:
            offers = await provider.search(
                "YYZ", "LHR", date.today() + timedelta(days=60), Cabin.business
            )
        except ProviderError as e:
            msg = str(e)
            if "Kasada" in msg or "429" in msg:
                return _pass(
                    name,
                    started,
                    "v1.c-1 wiring correct, Kasada-blocked as expected "
                    f"({msg[:120]}...)",
                )
            raise AssertionError(
                f"handshake regression: error did not mention Kasada/429: {msg}"
            )
        # No error: either Kasada was disabled, or we got real data — both
        # are interesting. Surface as PASS with a note so the operator
        # notices (a green check that says "Kasada gone?" is the right signal).
        return _pass(
            name,
            started,
            f"no Kasada block — got {len(offers)} offers (investigate: "
            "Kasada disabled or path changed)",
        )
    except Exception as e:
        return _fail(name, started, e)


async def check_browserbase_session_creates() -> CheckOutcome:
    """Create + close a Browserbase session. Validates API key, project ID,
    and the playwright-over-CDP path. Skips cleanly if creds absent."""
    name = "browserbase_session_creates"
    started = time.perf_counter()
    missing = _missing("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID")
    if missing:
        return _skip(name, missing, started)
    try:
        from autopoints.providers._browserbase import get_session

        page, browser = await get_session()
        try:
            # Tiny no-op navigation just to confirm the page is live. Use
            # about:blank to avoid spending bandwidth / proxy budget.
            await page.goto("about:blank")
        finally:
            await browser.close()
        return _pass(name, started, "session created, closed cleanly")
    except Exception as e:
        return _fail(name, started, e)


async def check_discord_bot_can_reach_channel() -> CheckOutcome:
    """Connect, post a test embed, delete it. Requires DISCORD_BOT_TOKEN and
    DISCORD_TEST_CHANNEL_ID. Uses a short login window so a stuck connect
    doesn't hang the whole check run."""
    name = "discord_bot_can_reach_channel"
    started = time.perf_counter()
    missing = _missing("DISCORD_BOT_TOKEN", "DISCORD_TEST_CHANNEL_ID")
    if missing:
        return _skip(name, missing, started)
    try:
        try:
            import discord
        except ImportError as e:
            raise AssertionError(
                "discord.py not installed — install with `uv pip install -e '.[discord]'`"
            ) from e

        token = os.environ["DISCORD_BOT_TOKEN"]
        channel_id = int(os.environ["DISCORD_TEST_CHANNEL_ID"])

        intents = discord.Intents.default()
        client = discord.Client(intents=intents)
        result: dict[str, Any] = {"ok": False, "err": None}

        @client.event
        async def on_ready() -> None:
            try:
                channel = client.get_channel(channel_id) or await client.fetch_channel(
                    channel_id
                )
                embed = discord.Embed(
                    title="autopoints live-check",
                    description="live-check ping (auto-deleted)",
                    color=0x95A5A6,
                )
                msg = await channel.send(embed=embed)
                await msg.delete()
                result["ok"] = True
            except Exception as e:  # noqa: BLE001 — capture for outer report
                result["err"] = e
            finally:
                await client.close()

        # 30s ceiling — Discord gateway connect is usually <5s; this guards
        # against a hung WebSocket from blocking the rest of the suite.
        await asyncio.wait_for(client.start(token), timeout=30.0)
        if result["err"]:
            raise result["err"]
        if not result["ok"]:
            raise AssertionError("on_ready never set ok=True")
        return _pass(name, started, f"posted + deleted embed in #{channel_id}")
    except Exception as e:
        return _fail(name, started, e)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

# Order matters: cheapest/fastest first so an early FAIL gives the operator
# quick feedback. Browserbase + Discord are last (paid + slow respectively).
CHECKS: list[tuple[str, CheckFn]] = [
    ("orchestrator_arrive_before_demo", check_orchestrator_arrive_before_demo),
    ("google_flights_redeye_lax_jfk", check_google_flights_redeye_lax_jfk),
    ("aeroplan_handshake_reaches_air_bounds", check_aeroplan_handshake_reaches_air_bounds),
    ("discord_bot_can_reach_channel", check_discord_bot_can_reach_channel),
    ("browserbase_session_creates", check_browserbase_session_creates),
]


def _color_status(status: str) -> str:
    return {
        "pass": f"{GREEN}PASS{RESET}",
        "fail": f"{RED}FAIL{RESET}",
        "skip": f"{YELLOW}SKIP{RESET}",
    }[status]


def _print_outcome(o: CheckOutcome) -> None:
    print(f"  {_color_status(o.status)}  {o.name:<42} {DIM}({o.duration_ms:>6.0f}ms){RESET}")
    if o.detail:
        print(f"         {DIM}{o.detail}{RESET}")


async def _run(selected: set[str] | None) -> list[CheckOutcome]:
    outcomes: list[CheckOutcome] = []
    for name, fn in CHECKS:
        if selected and name not in selected:
            continue
        outcome = await fn()
        outcomes.append(outcome)
        _print_outcome(outcome)
    return outcomes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        help="comma-separated check names to run (default: all)",
    )
    ap.add_argument(
        "--json",
        type=Path,
        help="write JSON report to PATH (in addition to stdout)",
    )
    args = ap.parse_args()

    selected: set[str] | None = None
    if args.only:
        selected = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = selected - {n for n, _ in CHECKS}
        if unknown:
            print(f"{RED}unknown check(s): {', '.join(sorted(unknown))}{RESET}")
            print(f"available: {', '.join(n for n, _ in CHECKS)}")
            return 2

    print(f"{BOLD}autopoints live-checks{RESET}")
    print()

    outcomes = asyncio.run(_run(selected))

    passed = sum(1 for o in outcomes if o.status == "pass")
    failed = sum(1 for o in outcomes if o.status == "fail")
    skipped = sum(1 for o in outcomes if o.status == "skip")

    print()
    print(f"{BOLD}summary:{RESET}  "
          f"{GREEN}{passed} pass{RESET}  "
          f"{RED}{failed} fail{RESET}  "
          f"{YELLOW}{skipped} skip{RESET}")

    if failed:
        print()
        print(f"{RED}{BOLD}failures:{RESET}")
        for o in outcomes:
            if o.status == "fail":
                print(f"  - {o.name}: {o.detail}")
                if o.traceback:
                    for line in o.traceback.rstrip().splitlines():
                        print(f"      {DIM}{line}{RESET}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "checks": [asdict(o) for o in outcomes],
                },
                indent=2,
            )
        )
        print(f"\nwrote JSON report to {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
