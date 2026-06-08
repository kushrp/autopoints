---
title: "feat: Points redemption v0 sprint — fli cash provider, time-of-day schema, arrival-time filter, Alaska direct award provider"
date: 2026-06-07
type: feat
status: active
origin: docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md
---

# feat: Points redemption v0 sprint

**Target repo:** autopoints (this repo)
**Origin requirements:** [`docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md`](../brainstorms/2026-06-07-points-redemption-sprint-requirements.md) (revised v0 cut)

---

## Summary

Replace the dying Amadeus cash provider with a `fli`-based Google Flights provider (validated end-to-end in probe), migrate the search schema to carry departure/arrival times so a `--arrive-before HH:MM<TZ>` filter can ship at the CLI + orchestrator, add Alaska Mileage Plan (Atmos) as the first direct-program live award provider via Browserbase + Playwright, and mark the broken Aeroplan endpoint deprecated. Foundation for direct-program coverage in phase 2 (AA / Delta / JetBlue) which is explicitly gated on a Stagehand probe.

## Problem Frame

The autopoints CPP-ranked award-search tool currently has:
- A cash provider (Amadeus) that loses its API access on 2026-07-17 with no new signups available
- A live award provider (Aeroplan) whose hostname returns NXDOMAIN
- A search schema (`FlightOffer` / `AwardOffer` / `SearchRequest` / `Watchlist`) that carries only `depart_date: date` — no time-of-day, no arrival timestamp, no arrival date for cross-midnight redeyes
- A `_signature()` dedup hash that would silently collapse two distinct redeyes on the same date if the schema gained time without a signature update
- A SQLite `watchlists` table with no column to persist an arrive-before filter

The forcing function for v0 (book LAX → NYC arriving < 08:00 ET on 2026-06-15) cannot be answered at the CLI today: Amadeus is the only cash provider and there is no filter for arrival time. This plan ships the foundational changes that unblock the question.

## Requirements

Carried from `docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md` "In Scope":

- **R1 (origin: In Scope row "Cash provider")** — `autopoints/providers/google_flights.py` returns live cash data for any route/date; replaces Amadeus in `build.py`'s provider registration.
- **R2 (origin: In Scope row "Schema migration")** — `FlightOffer`, `AwardOffer`, `SearchRequest` carry optional `departure_time` / `arrival_time` / `arrival_date` / `origin_tz` / `dest_tz` fields. Existing 62-test suite passes unchanged.
- **R3 (origin: In Scope row "CLI filter")** — `autopoints search ... --arrive-before HH:MM<TZ>` filters orchestrator output post-rank. FastAPI/MCP/Discord propagation explicitly **out of scope** in v0 per origin Deferred section.
- **R4 (origin: In Scope row "Watchlist schema")** — `watchlists` SQLite table gains `arrive_before_local` column. `Watchlist` dataclass carries the field. `_signature()` includes `arrival_time` when present (guard to preserve existing rows in `watchlist_seen`).
- **R5 (origin: In Scope row "Direct provider (1)")** — `autopoints/providers/alaska.py` returns live Alaska Mileage Plan (Atmos) award availability via Browserbase + Playwright. Returns `AwardOffer` with time fields populated.
- **R6 (origin: In Scope row "Aeroplan")** — `--use-live-aeroplan` flag remains opt-in (already default `False`); class docstring + Typer help-text record deprecation. No code removal.

Explicit non-goals (origin Deferred section): MCP server, Discord slash-command `--arrive-before`, JetBlue/AA/Delta direct providers, BrowserbaseAwardProvider shared base, Keychain auth helper, Bilt transfer ratios, NAS re-deploy, BA Avios iOS port, stale-availability re-verifier, live balance fetch.

## Key Technical Decisions

- **Google Flights mechanism: `fli` library, not Browserbase + Playwright.** Probe validated `fli` returns structured `FlightResult` with carrier / flight_number / departure_datetime / arrival_datetime / price / duration / stops. The `tfs=` protobuf approach hits Google directly via `curl_cffi`, no browser session, no Browserbase cost per query. Trade-off: undocumented protobuf schema with known instability risk. Fallback path (Browserbase + Playwright) deferred to phase 2 if `fli` breaks. *(Diverges from origin which assumed Browserbase + Playwright for Google Flights — probe-justified.)*

- **Schema migration uses optional-with-`= None` defaults**, never required. Cache blobs (`model_dump_json()` rows in `TTLCache`) round-trip safely on old data because Pydantic v2 `extra="ignore"` is the model default. No `cache.clear()` needed.

- **`_signature()` includes `arrival_time` only when present.** Guarding the new fields preserves the identity of existing rows in `watchlist_seen`. Without this guard, every watchlist hit appears `NEW` on the first run after migration.

- **Alaska provider uses Browserbase + Playwright (hand-rolled), not Stagehand.** Probe confirmed Alaska's site is a Web Component-based React SPA with no public XHR endpoint surfaced from cold load. Stagehand is reserved for AA/Delta in phase 2 where anti-bot (PerimeterX/Akamai) is the qualifying signal.

- **SQLite migration uses `sqlite_utils` `add_column` with idempotent guard.** `ALTER TABLE ADD COLUMN` is the safe path for nullable columns on populated tables; the guard makes the migration re-runnable.

- **Aeroplan: deprecation-only, no module removal.** Preserves the migration path if a new endpoint surfaces; minimal blast radius.

- **`fli` package is installed from GitHub** (`pip install git+https://github.com/punitarani/fli.git`), not PyPI — the PyPI name `fli` is unavailable; the GitHub repo installs as `flights` package. Adds `flights` to project deps.

- **Browserbase API key flows through `Settings` (pydantic-settings → `.env`)**, not Keychain. Keychain helper is phase 2 (its only consumer at v0 is this single key, which doesn't justify a new credential abstraction; per origin scope-guardian finding SG6).

## Output Structure

This plan modifies existing modules and adds two new provider files. No new directory hierarchy.

```text
autopoints/
├── providers/
│   ├── google_flights.py    # NEW
│   ├── alaska.py            # NEW
│   ├── aeroplan.py          # MODIFIED (docstring deprecation)
│   ├── base.py              # unchanged
│   ├── amadeus.py           # unchanged (no consumer after build.py edit)
│   ├── static_charts.py     # unchanged
│   └── demo.py              # unchanged
├── search/
│   ├── models.py            # MODIFIED (schema migration)
│   ├── orchestrator.py      # MODIFIED (post-rank filter)
│   └── build.py             # MODIFIED (provider wiring, BuildOptions)
├── watchlists.py            # MODIFIED (dataclass + SQLite + _signature)
├── watchlist_runner.py      # MODIFIED (thread new flag + arrive_before_local)
├── cli/
│   ├── main.py              # MODIFIED (--arrive-before flag + deprecation)
│   └── watchlist.py         # MODIFIED (--arrive-before for add + run)
└── config.py                # MODIFIED (browserbase_api_key)

tests/
├── test_google_flights.py   # NEW
├── test_alaska.py           # NEW
├── test_orchestrator.py     # MODIFIED (filter scenarios + back-compat)
└── test_watchlists.py       # MODIFIED (signature + migration scenarios)

pyproject.toml               # MODIFIED (add flights, browserbase deps; promote playwright)
Dockerfile                   # MODIFIED (install extras for runtime)
docs/STRATEGY.md             # already updated in brainstorm phase
```

---

## Implementation Units

### U1. Schema migration: time-of-day fields + watchlist column + _signature update

**Goal:** Add optional time-of-day fields to all search schemas. SQLite watchlist table gains the persisted filter column. `_signature()` includes arrival time when present so two distinct redeyes don't collapse to one signature.

**Requirements:** R2, R4

**Dependencies:** none — foundational unit, blocks U2, U3, U4.

**Files:**
- `autopoints/search/models.py` (modify) — add fields to `FlightOffer`, `AwardOffer`, `SearchRequest`
- `autopoints/watchlists.py` (modify) — `Watchlist` dataclass + `_signature()` + idempotent SQLite migration via `sqlite_utils.Database` (or inline `PRAGMA table_info` guard) + positional INSERT update to named columns
- `tests/test_watchlists.py` (modify) — extend `_redemption()` helper with time fields, add signature-collision test, add migration-idempotence test
- `tests/test_orchestrator.py` (modify) — extend `_StubAward` / `_StubCash` to optionally populate time fields

**Approach:**
1. Add to `FlightOffer` and `AwardOffer`:
   - `departure_time: time | None = None`
   - `arrival_time: time | None = None`
   - `arrival_date: date | None = None` (handles cross-midnight redeyes — e.g. LAX 22:25 → JFK 07:13 next day)
   - `origin_tz: str | None = None` (IANA name, e.g. "America/Los_Angeles")
   - `dest_tz: str | None = None`
2. Add to `SearchRequest`:
   - `arrive_before_local: str | None = None` (raw "HH:MM<TZ>" string, parsed by orchestrator; `time` + `tz` separately would force timezone-resolution earlier than needed)
3. Add to `Watchlist` dataclass: `arrive_before_local: str | None = None`
4. Migration: at `WatchlistStore.__init__`, after the existing `CREATE TABLE IF NOT EXISTS`, run `PRAGMA table_info(watchlists)` and `ALTER TABLE watchlists ADD COLUMN arrive_before_local TEXT` if the column is missing. Idempotent.
5. `_signature(r)`: append `|{arr}` segment where `arr = f"{r.award_offer.arrival_date.isoformat()}T{r.award_offer.arrival_time.isoformat()}"` when both are set, else empty string. Existing rows in `watchlist_seen` retain their identity.
6. Update `Watchlist.add()`'s positional `INSERT INTO watchlists VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)` to named columns (`INSERT INTO watchlists (id, origin, ...) VALUES (...)`), so adding a column doesn't require renumbering placeholders.
7. Update `_row_to_watchlist()` to index columns by name via `sqlite3.Row` factory (set `conn.row_factory = sqlite3.Row` in `WatchlistStore.__init__`).

**Patterns to follow:**
- Pydantic v2 idioms already used in `autopoints/search/models.py`: explicit defaults, `StrEnum`, `BaseModel`, `Field(...)`. New optional fields MUST have `= None` default (Pydantic v2 dropped the implicit-None default).
- `from __future__ import annotations` at top of every module (already convention).
- mypy strict mode (set via `pyproject.toml`) — full return-type annotations on every function.

**Test scenarios:**
- Existing 62 tests pass unchanged (back-compat).
- `FlightOffer` round-trips JSON when new fields are unset (omitted in output) and when set (preserved through `model_dump_json` → `FlightOffer(**)`).
- Cached `model_dump_json()` blobs written before migration deserialize cleanly with new fields defaulting to `None`.
- `_signature()` for two `RedemptionResult`s with same date/cabin/carrier/points but different `arrival_time` returns different signatures.
- `_signature()` for a `RedemptionResult` without arrival fields returns identical signature to a pre-migration row's hash (no breakage of existing `watchlist_seen` data).
- `WatchlistStore.__init__` is idempotent — running twice does not error when column already exists.
- `WatchlistStore.add(Watchlist(arrive_before_local="08:00ET"))` round-trips through `list()` correctly.

**Verification:** `uv run pytest -q` passes (62 prior + new). `python -c "from autopoints.search.models import FlightOffer; FlightOffer(provider='x', origin='LAX', destination='JFK', depart_date=..., cabin='economy', carrier='B6', cash_cents=40900, arrival_time=..., arrival_date=...)"` succeeds.

---

### U2. Google Flights cash provider via `fli` library

**Goal:** `autopoints/providers/google_flights.py` exposes `GoogleFlightsProvider(CashProvider)` returning live `FlightOffer[]` for any route/date. Replaces Amadeus as the registered cash provider in `build.py`.

**Requirements:** R1

**Dependencies:** U1 (uses new `departure_time` / `arrival_time` / `arrival_date` fields on `FlightOffer`)

**Files:**
- `autopoints/providers/google_flights.py` (new) — `GoogleFlightsProvider` class implementing `CashProvider`
- `autopoints/search/build.py` (modify) — replace Amadeus branch with `GoogleFlightsProvider()` registration (always-on; no API key required for `fli`)
- `pyproject.toml` (modify) — add `"flights"` to base dependencies (note: PyPI name is `flights`, installs from `pip install git+https://github.com/punitarani/fli.git`)
- `tests/test_google_flights.py` (new) — provider unit tests with `respx`-mocked `fli` responses (or fixture-based parse-only tests if `fli` calls the network directly)

**Approach:**
1. Map `fli.models.FlightResult.legs` → `FlightOffer`:
   - For a nonstop `FlightResult` with 1 leg → 1 `FlightOffer`
   - For multi-leg → 1 `FlightOffer` with `flight_numbers` concatenated; `departure_time` from first leg, `arrival_time` + `arrival_date` from last leg
   - `cash_cents = int(round(result.price * 100))`
   - `currency = "USD"` (passable via fli's `currency` kwarg; default USD)
   - `duration_minutes = result.duration`
   - `stops = result.stops`
   - `carrier` = first leg's airline IATA code (e.g. "B6" for JetBlue)
2. Build `FlightSearchFilters` from `(origin, destination, depart_date, cabin, passengers)`:
   - `trip_type=TripType.ONE_WAY` (date_window expansion happens at orchestrator layer, not provider)
   - `seat_type` mapped from `Cabin` enum
   - `stops=MaxStops.ANY` (filtering by stops belongs in user-facing filters, not the provider)
3. Wrap `SearchFlights().search(filters, top_n=20)` in `asyncio.to_thread(...)` since `fli` is sync. Pattern: `await asyncio.to_thread(SearchFlights().search, filters, 20)`.
4. Error handling: catch `fli.search.exceptions.SearchClientError`, `SearchHTTPError`, `SearchTimeoutError` → re-raise as `ProviderError`. Orchestrator already swallows these into `outcome.warnings`.
5. Adapter shape lives in `_to_flight_offer(self, result: FlightResult) -> FlightOffer | None` (returns `None` for unparseable rows; defensive parsing pattern from `amadeus.py`).
6. `name = "google_flights"`.

**Patterns to follow:**
- Provider structure from `autopoints/providers/amadeus.py`: defensive `_parse_offers()` that skips malformed rows, returns warnings via `ProviderError`.
- Async wrap of sync work: existing codebase pattern (e.g. `static_charts.py` is sync-in-async).
- HTTP mocking with `respx` (already a dev dep) for tests that exercise the parse path.

**Test scenarios:**
- `GoogleFlightsProvider.search(LAX, JFK, 2026-06-14, economy, 1)` returns at least one `FlightOffer` with `arrival_date == 2026-06-15` (the redeye case). *(Marked `@pytest.mark.e2e` if calling live; mocked with fixture otherwise.)*
- Parser maps `fli.FlightResult` with two legs to a single `FlightOffer` with `flight_numbers = ["AA1362", "AA1587"]`, `departure_time` from first leg, `arrival_time`/`arrival_date` from second leg.
- Parser handles `fli` returning `None` (no flights) → provider returns `[]`.
- Parser handles malformed `FlightResult` (missing `legs` or empty `legs`) → row skipped, no exception.
- `SearchHTTPError` from fli wraps to `ProviderError` with `provider="google_flights"` in the message.

**Verification:** `uv run python -c "import asyncio; from datetime import date; from autopoints.providers.google_flights import GoogleFlightsProvider; offers = asyncio.run(GoogleFlightsProvider().search('LAX', 'JFK', date(2026,6,14), 'economy', 1)); print([o.carrier, o.cash_cents/100, o.arrival_time, o.arrival_date for o in offers[:3]])"` prints 3 real offers.

---

### U3. `--arrive-before` CLI flag + orchestrator post-rank filter + watchlist runner plumb

**Goal:** Add `--arrive-before HH:MM<TZ>` to `autopoints search` and `autopoints watchlist add`; orchestrator applies it as a post-rank filter against `arrival_time` + `arrival_date`; watchlist runner threads the persisted filter through `BuildOptions` / orchestrator.

**Requirements:** R3, R4

**Dependencies:** U1 (uses `arrive_before_local` on `SearchRequest` + `Watchlist`, and `arrival_time` on offers)

**Files:**
- `autopoints/search/orchestrator.py` (modify) — add `_filter_arrive_before()` helper; call it on `outcome.redemptions` between line 112 (last `outcome.redemptions.append(...)`) and `return outcome`
- `autopoints/cli/main.py` (modify) — add `--arrive-before` Typer option to `search` command; build `SearchRequest` with the parsed value
- `autopoints/cli/watchlist.py` (modify) — add `--arrive-before` Typer option to `add`; persist on `Watchlist`; thread through `run`
- `autopoints/watchlist_runner.py` (modify) — `run_one()` / `run_all()` read `wl.arrive_before_local`, set on the `SearchRequest` passed to orchestrator
- `tests/test_orchestrator.py` (modify) — filter scenarios

**Approach:**
1. Filter format: `HH:MM<TZ>` where `TZ ∈ {"ET", "CT", "MT", "PT"}` (initial set; expandable). Parser maps `ET` → `"America/New_York"`, etc. Use `python-dateutil` (already a dep) or stdlib `zoneinfo` to resolve.
2. Filter logic: a redemption passes the filter iff `(award_offer.arrival_date, award_offer.arrival_time)` resolved in `award_offer.dest_tz` is `<` parsed filter. If either field is None (chart-floor result with no flight times), the redemption **passes** the filter (chart-floor results are kept; user sees them with `confidence: low` annotation). Document this behavior in the orchestrator docstring.
3. Watchlist persistence: store the raw string ("08:00ET"), not parsed components — defers resolution to runtime in case TZ rules ever change.
4. CLI help text: `--arrive-before HH:MM<TZ>, e.g. "08:00ET"`. Add examples to `autopoints search --help` output.

**Patterns to follow:**
- Typer `Annotated[T, typer.Option(...)]` shape used everywhere in `cli/main.py`.
- Orchestrator post-rank pattern: filter `outcome.redemptions` in place before `outcome.best_per_program()` is implicitly called by downstream renderers.

**Test scenarios:**
- Filter "08:00ET" against a redemption with `arrival_time=07:13`, `arrival_date=2026-06-15`, `dest_tz="America/New_York"` → passes.
- Filter "06:00ET" against the same → rejected.
- Filter "08:00ET" against a redemption with `arrival_time=None` (chart-floor) → passes (kept).
- Filter omitted (None) → no filtering happens; all redemptions returned.
- Filter "25:00ET" (invalid HH) → CLI exits with error before orchestrator runs.
- Filter "08:00XX" (unknown TZ) → CLI exits with error.
- Watchlist created with `arrive_before_local="08:00ET"` and run → orchestrator receives the filter via `SearchRequest`.

**Verification:** `uv run autopoints search LAX JFK 2026-06-14 --arrive-before 08:00ET --cabin economy` prints a ranked table where every visible row's `arrival_time` (when present) is < 08:00 ET on 2026-06-15.

---

### U4. Alaska direct award provider via Browserbase + Playwright

**Goal:** `autopoints/providers/alaska.py` exposes `AlaskaProvider(AwardProvider)` returning live Mileage Plan (Atmos) award availability for a route/date, including partner awards (Cathay/JAL/Qatar sweet spots).

**Requirements:** R5

**Dependencies:** U1 (populates new time fields on `AwardOffer`)

**Files:**
- `autopoints/providers/alaska.py` (new) — `AlaskaProvider` class
- `autopoints/providers/_browserbase.py` (new) — minimal helper: `async def get_session() -> tuple[Page, Cleanup]` that creates a Browserbase session and returns a Playwright `Page`. NOT a base class — just shared session-creation code. (Keeps the unit small; resists the speculative-abstraction trap flagged in origin scope-guardian SG2.)
- `autopoints/search/build.py` (modify) — append `AlaskaProvider()` to `award_providers` when `opts.use_live_alaska` is True; add `use_live_alaska` to `BuildOptions`
- `autopoints/cli/main.py` (modify) — add `--live-alaska / --no-live-alaska` Typer option (default `False` mirroring `--live-aeroplan`)
- `autopoints/watchlist_runner.py` (modify) — thread `use_live_alaska` through `run_one()` / `run_all()`
- `autopoints/config.py` (modify) — add `browserbase_api_key: str = ""` + `browserbase_project_id: str = ""` to `Settings`
- `pyproject.toml` (modify) — add `"browserbase>=1.12"` and promote `"playwright>=1.58"` from dev to base deps (or add new `[browserbase]` extra and update Dockerfile install)
- `Dockerfile` (modify) — extend `pip install --target=/install ".[discord,browserbase]"` (or whatever extras name we choose); skip `playwright install chromium` since Browserbase provides the browser
- `tests/test_alaska.py` (new) — Browserbase live calls marked `@pytest.mark.e2e`; parse-only tests with HTML fixtures for offline coverage

**Approach:**
1. **Session bootstrap** (in `_browserbase.py`): `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` from `Settings`; `Browserbase(api_key=...).sessions.create(project_id=..., proxies=[{type: "browserbase", geolocation: {country: "US"}}])` for stealth + residential IP. Return `Page` from `async_playwright().chromium.connect_over_cdp(session.connect_url).contexts[0].pages[0]`.
2. **Form driving** (in `alaska.py`):
   - Navigate to `https://www.alaskaair.com/`
   - Wait for `borealis-expanded-booking-widget` to render (`page.wait_for_selector('borealis-expanded-booking-widget')`)
   - Click `radio[name="One way"]`
   - Click `checkbox[name="Use points"]`
   - Click `combobox: From`, `press_sequentially("LAX", delay=80)`, wait for option list, click `option` with text containing "LAX"
   - Same for destination
   - Click the date input, type `M/D/YYYY` format, press Enter, then Escape to close picker
   - Click `Search flights`
3. **Result extraction**:
   - Wait for the award-results layout to render (`page.wait_for_url("**/shopping/**")` or `page.wait_for_selector('[data-testid="flight-result"]')` — confirm during implementation)
   - For each result row, extract: carrier (IATA), flight number, departure time, arrival time, points required, taxes, fare class, stops
   - Parse times: site shows local time at origin / destination; resolve `arrival_date` by checking for "+1" overnight indicator typical on redeye displays
4. **Error handling**:
   - If form fields don't render in 15s → `ProviderError("Alaska award search UI did not load")`
   - If the search button click yields no results in 30s → `ProviderError("Alaska search timed out")`
   - If Browserbase session creation fails (429, no credits) → `ProviderError(f"Browserbase: {e}")`
5. **Rate limit**: provider-internal `asyncio.Semaphore(1)` per instance so concurrent calls (from orchestrator fan-out across date_window days) serialize. Phase-2 will introduce a global Browserbase semaphore.
6. **Cache TTL**: 6 hours (matches `AWARD_TTL`).
7. **`program_code = "AS"`**, **`name = "alaska"`**.

**Patterns to follow:**
- Provider structure from `autopoints/providers/aeroplan.py` (the broken one): same shape for `search()` signature, same `ProviderError` raising pattern.
- Playwright form-driving: per research findings, use `press_sequentially(text, delay=80)` for typeahead (not `fill`), `get_by_role` for clicks (not CSS).
- Browserbase session-create: per docs, set `browserSettings.solveCaptchas: True` to dodge phase-1 CAPTCHA dead-ends.

**Execution note:** Start with the form-driving flow against a live Browserbase session in a one-off script (`scripts/spike_alaska.py` — not committed) to map element selectors and result-row structure. Encode discovered selectors into `alaska.py` once flow works end-to-end. This is the highest-uncertainty unit; a one-day spike before integration is appropriate.

**Test scenarios:**
- Parse-only: given a fixture HTML of an Alaska award results page, `_parse_results()` returns expected `AwardOffer[]` with carriers, points, time fields. *(Multiple fixtures: 1-stop, nonstop, partner-marketed, sold-out date.)*
- Marked `@pytest.mark.e2e`: live call for LAX→JFK 2026-06-14 returns at least one `AwardOffer` (might be empty if no award space — assert no exception either way).
- Browserbase session-create failure raises `ProviderError`.
- Provider respects internal semaphore (two concurrent `search()` calls serialize).
- Missing `BROWSERBASE_API_KEY` raises `ProviderError("Browserbase not configured")` at provider construction, not at first search.

**Verification:** `BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... uv run autopoints search LAX JFK 2026-06-14 --cabin economy --live-alaska` prints at least one row with `program=AS` and a non-zero points value (or surfaces a warning if Alaska has no LAX-JFK award space on the date — verified by manual check on alaskaair.com).

---

### U5. Aeroplan deprecation note

**Goal:** Record the deprecation of the broken Aeroplan live provider in code and CLI help text. No functional change — flag is already opt-in defaulting to False.

**Requirements:** R6

**Dependencies:** none

**Files:**
- `autopoints/providers/aeroplan.py` (modify) — add deprecation note to class docstring referencing the NXDOMAIN endpoint and the phase-2 follow-up
- `autopoints/cli/main.py` (modify) — extend the `--use-live-aeroplan` / `--no-use-live-aeroplan` help text with "(deprecated 2026-06-07: endpoint NXDOMAIN; left in place for phase 2 repair)"
- `autopoints/api/main.py` (modify) — same help text update on the `/api/search` `live_aeroplan` query param

**Approach:**
- Class docstring (`AeroplanProvider`): `"""Air Canada Aeroplan live award search. DEPRECATED 2026-06-07: hostname `akamai-akwa-aeroplan.aircanada.com` returns NXDOMAIN. Use `--no-use-live-aeroplan` (default). Repair to a new endpoint is a phase-2 task; see docs/STRATEGY.md."""`
- Typer help text update only — no behavior change.
- Update `tests/test_api.py` if it asserts on the help string (search-and-replace).

**Patterns to follow:**
- Existing CLI help text style (one-line, lowercase first letter).

**Test scenarios:**
- `Test expectation: none -- documentation-only change. Existing 62-pass suite is sufficient to confirm no behavior regression.`

**Verification:** `uv run autopoints search --help | grep -A1 use-live-aeroplan` shows the deprecation note. `python -c "from autopoints.providers.aeroplan import AeroplanProvider; print(AeroplanProvider.__doc__)"` shows the deprecation text.

---

## Open Questions

- **Browserbase parallel session limits on user's plan.** Origin Dependencies/Assumptions: "User has an active Browserbase API key (env var BROWSERBASE_API_KEY)." Plan size on Browserbase determines concurrent-session ceiling; if Developer ($20) plan, the limit is 25 concurrent — sufficient for v0 (1 Alaska scraper + future expansion). If Free plan (3 concurrent), watchlist runner could hit the limit. Defer: verify plan tier before running watchlist runner unattended.
- **Alaska result-row selectors.** The one-day spike (per U4 Execution Note) is the discovery step. Selectors are likely `data-testid="..."` attributes on result-row Web Components; the exact attribute names are not visible from the homepage snapshot and must be discovered via DevTools at search-results render time. Defer: lock during the U4 spike.
- **`fli` schema drift risk.** `fli` parses Google's undocumented protobuf. If Google changes the protobuf shape (which has happened historically per `fli`'s issue tracker), the cash provider breaks until `fli` upstream patches. Phase-2 mitigation: a Browserbase + Playwright fallback adapter for Google Flights. v0 accepts the risk.

## Risks & Dependencies

| Risk | Mitigation |
|---|---|
| `fli` breaks against Google's protobuf without warning | Provider raises `ProviderError`; orchestrator surfaces in `outcome.warnings`; user gets chart-floor only until upstream fix or fallback adapter (phase 2) |
| Alaska Web Component selectors change | Provider raises `ProviderError`; tests with fixture HTML catch parse regressions; selectors live in one place (`alaska.py`) for fast repair |
| Browserbase session capacity exhausted | Per-provider semaphore + 429 retry-after honoring; phase-2 global semaphore for unattended watchlist runs |
| Watchlist signature breakage on migration | `_signature()` includes new fields only when present — existing `watchlist_seen` rows preserve identity; new rows get richer identity going forward |
| Pydantic v2 schema migration breaks downstream JSON consumers (FastAPI surface) | All new fields optional + Pydantic v2 `extra="ignore"` is default — old API consumers see new fields as omitted or null |
| Sunday flight booking misses if Alaska scraper lands later than expected | Decoupled — `fli` cash output (3 redeye options) plus manual checks on direct sites covers the booking decision independently |

## Deferred to Follow-Up Work

These are noted during planning but explicitly out of v0 scope. Each is a one-line marker; details live in `docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md` Phase 2 section.

- BrowserbaseAwardProvider shared base class (extract after 2-3 direct providers exist)
- JetBlue direct provider (Browserbase + Playwright)
- AA + Delta direct providers (gated on Stagehand probe — task #30 in tracker)
- FastMCP server wrapping FastAPI handlers
- `--arrive-before` propagation to FastAPI / Discord / MCP
- Keychain auth helper
- Bilt as a third transfer source
- BA Avios iOS API port from `timrogers/ba_rewards`
- Stale-availability re-verifier
- Live balance auto-fetch from logged-in sessions
- NAS re-deploy (already deployed; redeploy when v0 ships)
- Linux Docker credential storage strategy

## Acceptance: Outcome the plan must enable

Per the origin requirements doc Outcome section:

```text
autopoints search LAX NYC 2026-06-14 --arrive-before 08:00ET --pax 1 --cabin economy
```

returns a ranked list combining:
- ✅ Live cash baseline from Google Flights via `fli` for LAX→{JFK,LGA,EWR} on 2026-06-14 (U1 + U2)
- ✅ Live Alaska Mileage Plan award availability for the same date (U1 + U4)
- ✅ Chart-floor pricing for existing AC / BA / VS providers (unchanged — U5 deprecation note covers AC)
- ✅ Arrival-time filter applied at the orchestrator's post-rank step (U1 + U3)

## Sources & Research

External research that materially shaped this plan:

- `punitarani/fli` (https://github.com/punitarani/fli) — Python library for Google Flights, `curl_cffi` + protobuf. Probe-validated 2026-06-07. Shapes U2.
- `browserbase/stagehand-python` (https://github.com/browserbase/stagehand-python) — v3.21.0 May 2026; confirms Stagehand is Python-available, unblocks the phase-2 AA/Delta probe (deferred from v0).
- Browserbase Python SDK docs (https://docs.browserbase.com/reference/sdk/python) — session creation, residential proxies, 429 backoff. Shapes U4.
- Playwright async API (https://playwright.dev/python/docs/network) — `press_sequentially`, `expect_response`. Shapes U4 form-driving.
- Pydantic v2 migration guide (https://docs.pydantic.dev/latest/migration/) — optional-field default rule (`= None` required). Shapes U1.
- `lg/awardwiz` (archived) Alaska scraper — reference for the form-driven pattern that's the only known live path to Alaska award data. Shapes U4 approach.
- `flightplan-tool/flightplan` (unmaintained) Alaska adapter — confirms no public JSON XHR endpoint. Shapes U4 decision to use Browserbase + Playwright rather than HTTP.

Probe runs:
- `fli` LAX→JFK 2026-06-14: returned 5+ redeye options including B6 1024 (22:25→07:13 6/15, $409), DL 960 (21:10→05:25 6/15, $539), AA 1362+1587 (19:30→05:44 6/15, $357). Validated cash provider.
- alaskaair.com homepage: booking widget renders, "Use points" toggle present, no URL-driven prefill (form-driving required, not deep-link).
