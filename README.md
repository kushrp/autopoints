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

### CLI

```sh
autopoints search JFK PHX 2026-06-15
autopoints search JFK PHX 2026-06-15 --window 2 --cabin business
autopoints search JFK PHX 2026-06-15 --demo              # synthetic data, no API key needed
autopoints search JFK PHX 2026-06-15 --refresh           # bypass cache
autopoints search JFK PHX 2026-06-15 --live-aeroplan     # hit Aeroplan's live endpoint
```

Output: a ranked table — one row per `(transfer currency, loyalty program)` pair, sorted by effective CPP, color-coded by verdict (`great` / `good` / `ok` / `bad`).

### Web UI

```sh
autopoints-server   # serves http://127.0.0.1:8000
```

Open the URL — single-page app with a search form, ranked results table, and a date-grid heatmap of best CPP per program per day. Demo mode is on by default so the UI works without API credentials. Toggle it off and configure Amadeus credentials in `.env` for real cash data.

### HTTP API

```
GET  /api/health         → {status, version}
GET  /api/programs       → valuations + transfer ratios + supported charts + thresholds
POST /api/search         → ranked redemptions for a route + window
```

`POST /api/search` body:

```json
{
  "origin": "JFK",
  "destination": "PHX",
  "depart_date": "2026-06-15",
  "window_days": 2,
  "cabin": "economy",
  "passengers": 1,
  "demo": true,
  "live_aeroplan": false
}
```

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

- **Cash:**
  - `AmadeusProvider` — official Self-Service API, free tier (2k/mo).
  - `DemoCashProvider` — synthetic per-mile pricing, used when `--demo` is set or no Amadeus key is configured.
- **Award:**
  - `StaticChartProvider("AC" | "BA" | "VS")` — distance-based chart lookup for Aeroplan, BA Avios, Virgin Atlantic Flying Club. Works offline. Returns the chart-floor (saver) cost; doesn't confirm live availability.
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

27 tests covering CPP math, transfer ratios, distance/chart lookup, orchestrator behavior (caching, force-refresh, partial failure, date windows), and HTTP API endpoints (health, programs, search, validation).

## Repo layout

```
autopoints/
  cli/main.py                  # Typer entrypoint
  api/
    main.py                    # FastAPI app: GET /, /api/health, /api/programs, POST /api/search
    models.py                  # API request/response schemas
    server.py                  # uvicorn launcher
  web/
    templates/index.html       # single-page app
    static/{styles.css,app.js} # vanilla JS UI, no build step
  config.py                    # pydantic-settings
  search/
    models.py                  # SearchRequest, FlightOffer, AwardOffer, RedemptionResult
    orchestrator.py            # async fan-out + caching
    build.py                   # shared provider wiring (CLI + API)
  providers/
    base.py                    # CashProvider / AwardProvider ABCs
    amadeus.py                 # cash via Amadeus Self-Service
    demo.py                    # synthetic cash data for keyless demos
    aeroplan.py                # live Aeroplan award search (reverse-engineered)
    static_charts.py           # offline chart-floor pricing
  pricing/cpp.py               # CPP, verdict, transfer math
  programs/
    valuations.json            # cents/point per program (TPG-sourced)
    transfer_ratios.json       # UR/MR → partner ratios
    transfer_bonuses.json      # active bonuses with date windows
    airports.json              # IATA → lat/lon
    award_charts/{ac,ba,vs}.json # Aeroplan / BA Avios / Virgin Atlantic charts
  cache/store.py               # SQLite TTL cache
tests/                         # pytest (CPP, geo, charts, orchestrator, API)
```

## What's next

- **Flying Blue + United chart providers.** Flying Blue is fully dynamic (no chart fallback feasible).
- **Live award providers beyond Aeroplan.** BA Avios next (distance chart already in place — just need the live endpoint adapter); Virgin Atlantic and Flying Blue after.
- **Transfer bonuses live tracking.** Currently manual JSON; could scrape doctorofcredit / FrequentMiler.
- **Watchlists.** Saved routes re-run nightly, notify on new sub-2.0¢ redemptions.
- **More airports.** Extend `programs/airports.json`; OpenFlights `airports.dat` is a good source for full coverage.

## Caveats

- Reverse-engineered airline endpoints are brittle by definition. Schema drift is normal; `static_charts` is the safety net.
- This is a personal-use tool. Distributing publicly invites C&D letters from airlines; out of scope.
- Aeroplan returns taxes in CAD by default; the CPP layer notes this in the output. Convert manually if you care about precision below ~5%.
- Static valuations should be refreshed monthly from TPG / Frequent Miler. The JSON has a `last_reviewed` field — set a calendar reminder.
