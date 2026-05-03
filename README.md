# autopoints

Automated points-redemption value engine. Given a route + date, fetch cash prices, look up award (points) prices across Chase Ultimate Rewards and Amex Membership Rewards transfer partners, and rank redemptions by cents-per-point (CPP).

The point: stop guessing whether 12,500 Aeroplan points is a "good deal" for that JFK→PHX flight. The tool computes `(cash − taxes) / points` and tells you.

## Install

Requires Python 3.11+.

```sh
uv venv --python 3.11
uv pip install -e ".[dev]"
cp .env.example .env
# Fill in AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET. Free tier: 2k calls/mo.
# Sign up at https://developers.amadeus.com/register
```

## Usage

```sh
autopoints search JFK PHX 2026-06-15
autopoints search JFK PHX 2026-06-15 --window 2 --cabin business
autopoints search JFK PHX 2026-06-15 --refresh           # bypass cache
autopoints search JFK PHX 2026-06-15 --live-aeroplan     # hit Aeroplan's live endpoint
```

Output: a ranked table — one row per `(transfer currency, loyalty program)` pair, sorted by effective CPP, color-coded by verdict (`great` / `good` / `ok` / `bad`).

## How it works

```
SearchRequest ─┬──► CashProvider(s) ─────► FlightOffer[]
               │
               └──► AwardProvider(s) ────► AwardOffer[]
                                              │
                  pricing.cpp ◄───────────────┘
                       │
                       ▼
                  RedemptionResult[] sorted by effective CPP
```

- **Cash:** Amadeus Self-Service (official, free tier).
- **Award:**
  - `StaticChartProvider("AC")` — Aeroplan's published distance-based chart. Works offline. Returns the saver-bucket floor; doesn't confirm live availability.
  - `AeroplanProvider` — reverse-engineered hit against Aeroplan's public award-search endpoint. Enable with `--live-aeroplan`. Schema is undocumented; brittle.
- **Caching:** SQLite at `~/.autopoints/cache.db`. Cash TTL 1h, award TTL 6h. `--refresh` to bypass.
- **Valuations + transfer ratios:** static JSON in `autopoints/programs/`. Refresh manually from TPG / Frequent Miler.

## CPP math

```
cpp = (cash_cents − award_taxes_cents) / points_required
```

Verdict thresholds (defaults, configurable in `.env`):

| CPP                  | Verdict |
|---------------------:|---------|
| ≥ 2.0¢               | great   |
| ≥ 1.5¢               | good    |
| ≥ program valuation  | ok      |
| <  program valuation | bad     |

Effective CPP additionally applies any active transfer bonus from `programs/transfer_bonuses.json`.

## End-to-end verification

The plan's verification steps (see `/root/.claude/plans/`):

1. **JFK → PHX, 2026-06-15, economy.** Open Google Flights for the same route — Amadeus should be within ~5%.
2. **Award cross-check:** open `aircanada.com` award search — `--live-aeroplan` output should match exactly.
3. **CPP boundary:** $180 cash + 12,500 AC pts + $5.60 taxes = 1.39¢ → `bad`. $300 cash same award = 2.36¢ → `great`.
4. **Cache:** rerun within 1h, second run completes in <100ms.
5. **Failure isolation:** with bogus credentials, the failing provider produces a warning row, the search still returns whatever else worked.

## Tests

```sh
.venv/bin/pytest
```

22 tests covering CPP math, transfer ratios, distance/chart lookup, and orchestrator behavior (caching, force-refresh, partial failure, date windows).

## Repo layout

```
autopoints/
  cli/main.py                  # Typer entrypoint
  config.py                    # pydantic-settings
  search/
    models.py                  # SearchRequest, FlightOffer, AwardOffer, RedemptionResult
    orchestrator.py            # async fan-out + caching
  providers/
    base.py                    # CashProvider / AwardProvider ABCs
    amadeus.py                 # cash via Amadeus Self-Service
    aeroplan.py                # live Aeroplan award search (reverse-engineered)
    static_charts.py           # offline chart-floor pricing
  pricing/cpp.py               # CPP, verdict, transfer math
  programs/
    valuations.json            # cents/point per program (TPG-sourced)
    transfer_ratios.json       # UR/MR → partner ratios
    transfer_bonuses.json      # active bonuses with date windows
    airports.json              # IATA → lat/lon
    award_charts/ac.json       # Aeroplan distance chart
  cache/store.py               # SQLite TTL cache
tests/                         # pytest
```

## What's next (post-MVP slices)

2. **Avios + Flying Blue providers.** BA Avios is distance-charted (good); Flying Blue is fully dynamic (no chart fallback).
3. **Transfer bonuses live tracking.** Currently manual JSON; could scrape doctorofcredit / FrequentMiler.
4. **FastAPI HTTP layer.** Same orchestrator behind a `POST /search` endpoint.
5. **UI.** React/Vite, sortable table + date-grid heatmap.
6. **Watchlists.** Saved routes re-run nightly, notify on new sub-2.0¢ redemptions.

## Caveats

- Reverse-engineered airline endpoints are brittle by definition. Schema drift is normal; `static_charts` is the safety net.
- This is a personal-use tool. Distributing publicly invites C&D letters from airlines; out of scope.
- Aeroplan returns taxes in CAD by default; the CPP layer notes this in the output. Convert manually if you care about precision below ~5%.
- Static valuations should be refreshed monthly from TPG / Frequent Miler. The JSON has a `last_reviewed` field — set a calendar reminder.
