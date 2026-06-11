# End-to-end testing

Three layers of automated coverage plus a manual checklist.

## 1. Unit + integration (default pytest)

```sh
.venv/bin/pytest
```

45 tests covering CPP math, transfer ratios, distance/chart lookup, orchestrator behavior, HTTP API, watchlist diff/persistence, and Discord embed formatting. No external deps. <1s.

## 2. HTTP + CLI smoke (`scripts/e2e.py`)

Boots a real uvicorn process on a free port and walks through every endpoint and CLI subcommand. Runs in ~3s.

```sh
./scripts/e2e.py             # full suite (API + CLI)
./scripts/e2e.py --api-only  # skip CLI steps
./scripts/e2e.py --keep      # leave the server running so you can inspect it
```

What it proves:
- `GET /` serves the SPA HTML with the form and bootstrap programs JSON
- Static assets serve
- `GET /api/health`, `/api/programs` return the expected shape
- `POST /api/search` returns ranked redemptions sorted by CPP
- IATA validation rejects malformed input
- Watchlist CRUD + run + diff cycle (first run flags NEW, second run flags as previously-seen)
- CLI `--help`, `search`, and `watchlist add/list/remove/run` produce the expected output

## 3. Browser end-to-end (Playwright)

Drives the real web UI in headless Chromium.

```sh
uv pip install --python .venv/bin/python -e ".[e2e]"
.venv/bin/playwright install chromium
.venv/bin/pytest -m e2e
```

Skips cleanly if the browser binary isn't installed.

What it proves:
- The page loads and the form renders
- Form submission round-trips through `/api/search` and renders the table
- Heatmap renders with populated cells when `window > 0`
- Row click expands details
- Sortable column header re-orders rows

Screenshots land in `tests/e2e/artifacts/` for postmortems.

## 4. Manual test plan

Some things aren't worth automating yet — walk through these before each release.

### 4a. Web UI

1. `autopoints-server` → open http://127.0.0.1:8000
2. Default form (JFK→PHX, today+60d, ±2, economy) — submit
   - Expect: results section appears within ~1s
   - Expect: ≥9 rows (3 programs × 3 transfer currencies)
   - Expect: heatmap appears with one row per program, one column per date, color-graded cells
3. Click a results row — expect details expand showing cash + award offers
4. Click "Effective CPP" header — expect rows resort
5. Uncheck "Use demo data", submit
   - Expect: live cash prices from Google Flights; if Google Flights is unreachable, a yellow warning banner appears and award rows still render via chart fallback
6. Toggle dark mode in OS — expect colors invert reasonably
7. Resize window narrow — expect layout doesn't break

### 4b. CLI

```sh
autopoints search JFK PHX 2026-06-15 --demo --window 2
autopoints search JFK PHX 2026-06-15 --demo --cabin business
autopoints search JFK LAX 2026-07-04 --demo                       # different route
autopoints search LHR CDG 2026-09-01 --demo                       # intl
autopoints search XYZ PHX 2026-06-15 --demo                       # unknown airport — expect graceful failure
autopoints watchlist add JFK PHX 2026-06-15 --threshold 2.0 --label "summer"
autopoints watchlist list
autopoints watchlist run --demo
autopoints watchlist run --demo --only-new        # should print nothing the second time
autopoints watchlist remove <id>
```

### 4c. Discord bot

Requires a bot token from https://discord.com/developers/applications.

```sh
uv pip install --python .venv/bin/python -e ".[discord]"
export DISCORD_BOT_TOKEN=...
export DISCORD_GUILD_ID=...           # optional but recommended for instant slash-command sync
export DISCORD_DEMO_MODE=1            # optional: force all searches into demo mode
autopoints-discord
```

In Discord:
- `/search origin:JFK destination:PHX depart_date_iso:2026-06-15 window:2 demo:true`
  → Expect: embed with up to 10 redemption rows
- `/watchlist add` then `/watchlist list` then `/watchlist run` then `/watchlist remove`

For nightly auto-runs:
```sh
export DISCORD_NOTIFY_CHANNEL_ID=...   # right-click channel → Copy ID
export DISCORD_RUN_INTERVAL_MINUTES=60
```
Bot will post NEW hits to that channel hourly.

## CI

GitHub Actions runs on every push (`.github/workflows/test.yml`):
- `test` job: ruff + pytest + smoke test (~30s)
- `e2e-browser` job: installs Playwright, runs `pytest -m e2e` (~90s, optional)

Failure artifacts (screenshots) upload automatically.

## On data sources

Two independent questions feed every redemption row:

1. **Cash price.** Default provider is **Google Flights** (via the `fli` library) — no API key required. Coverage is broad, though the undocumented backend can drift without notice; the provider raises a warning and falls back to chart-floor award results when that happens. Demo mode (default in the UI) bypasses it entirely with synthetic per-mile pricing.

2. **Award price.** Three static distance-based charts: Aeroplan (`AC`), British Airways Avios (`BA`), Virgin Atlantic Flying Club (`VS`). These cover most Star Alliance, oneworld, and SkyTeam partner redemptions via transfer from UR/MR. There's also a live Aeroplan adapter (`--live-aeroplan`) that hits the real public award-search endpoint — brittle by design, marked as such.

For "comprehensive" award coverage you'd add: live BA Avios (the chart works; live verifies availability), Flying Blue (no chart possible — dynamic pricing), and ideally direct United/Delta/AA inventory. seats.aero offers all of this commercially for ~$200/yr; we deliberately chose to reverse-engineer instead. See the slice plan in `/root/.claude/plans/` for the rationale.
