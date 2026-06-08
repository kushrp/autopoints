---
title: "feat: Alaska Mileage Plan (Atmos Rewards) selector-discovery spike + provider implementation"
date: 2026-06-08
type: feat
status: active
origin: docs/plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md (U4 partial-ship)
---

# feat: Alaska selector-discovery spike + AlaskaProvider implementation

**Target repo:** autopoints (this repo)
**Parent plan:** [`docs/plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md`](2026-06-07-001-feat-points-redemption-v0-sprint-plan.md) — v0 U4 partial-shipped with the wiring (`AlaskaProvider`, `_browserbase.py`, BuildOptions flag, CLI `--live-alaska`, watchlist runner threading, stub tests) but no scraper body. This plan finishes U4.

---

## Summary

The v0 sprint shipped every Alaska Mileage Plan integration surface *except* the form-driving + result-parsing body. `autopoints/providers/alaska.py:search()` raises `ProviderError("selector-discovery spike pending")` so the wiring is testable today and the orchestrator already surfaces the message as a warning. The remaining work is mostly empirical: Alaska's homepage (rebranded to Atmos Rewards in August 2025) is heavily Web Component-based (`auro-formkit`, `planbook-radio-group`, `borealis-expanded-booking-widget`) and the selectors must be observed against a live render before they can be encoded. AwardWiz's archived Alaska scraper (Sep 2024) used a CDP-driven flow that's the closest published reference for the form sequence.

This plan slices the work into a one-day selector-discovery spike (uncommitted script, captured selectors live in `docs/probes/alaska-selectors.md`), an encoding pass on `AlaskaProvider.search()`, parse-only + live-marked tests, and a final end-to-end wiring verification. The output is a working `--live-alaska` flag that returns live `AwardOffer` rows for LAX→JFK on the v0 forcing-function date (2026-06-14), with arrival-time fields populated so the `--arrive-before` filter actually fires against Alaska results.

## Problem Frame

After the v0 ship, the autopoints CPP-ranked award-search tool has:
- A working cash provider (Google Flights via `fli`) returning structured times.
- A working `--arrive-before` filter that fires against any populated `arrival_time` (post-PR-4 fix).
- A `AlaskaProvider` class that's instantiable, registered through `BuildOptions.use_live_alaska`, threaded through the watchlist runner, and exposed via `--live-alaska` — but `search()` always raises.
- A `_browserbase.get_session()` helper that creates a Browserbase session and returns a Playwright `Page`. Validated against alaskaair.com cold load during the v0 brainstorm probe.
- Chart-floor providers (AC, BA, VS) covering partner sweet spots numerically but not by *actual availability*.

The forcing function is now: "show me LAX→JFK 2026-06-14 with award space, ranked, including Alaska partner sweet spots." Today the `--live-alaska` flag emits a warning saying the spike hasn't run. The user has to fall back to manual checks on alaskaair.com for the partner-availability question (Cathay JFK→HKG F at 70k, JAL longhaul J ~60k, Qatar QSuite ~70k) — exactly the value-prop the program exists for.

The forcing test case for *this* plan: `autopoints search LAX JFK 2026-06-14 --cabin economy --live-alaska` must print at least one ranked row sourced from Alaska's live award search (or surface a clear "no award space" outcome if the date is sold out, verified independently against alaskaair.com).

## Requirements

Each requirement traces to a concrete part of the parent plan's U4 acceptance criteria and the v0 brainstorm's Phase-2 Alaska section:

- **R1 (origin: parent plan U4 "Execution note" + v0 brainstorm "Direct provider (1)")** — A one-off interactive spike script (`scripts/spike_alaska.py`, **NOT committed**) drives the Alaska homepage's award search for a known route/date, captures the relevant Web Component selectors and result-row structure, and outputs them to `docs/probes/alaska-selectors.md`. Selectors recorded include: `from` combobox, `to` combobox, date input, "Use points" toggle, "One way" radio, search button, results container, result-row, points cell, taxes cell, departure-time cell, arrival-time cell, "+1 day" indicator, partner-marketed indicator (separates Cathay/JAL/Qatar metal from Alaska-flown segments).

- **R2 (origin: parent plan U4 "Approach" steps 2-3)** — `AlaskaProvider.search()` no longer raises; it drives the form via `_browserbase.get_session()`, waits for results, parses rows into `AwardOffer[]` populating `points`, `taxes_cents`, `cabin`, `operating_carrier`, `fare_class`, `departure_time`, `arrival_time`, `arrival_date`, `dest_tz` (for the destination airport — pulled from a small lookup or derived via airline-IATA → IANA mapping). `program_code` stays `"AS"`. Partner-marketed rows (Cathay metal etc.) MUST be distinguishable from Alaska-metal rows — encoded in `operating_carrier` (the actual flying airline) with the marketing layer in `fare_class` if the UI exposes it.

- **R3 (origin: parent plan U4 "Test scenarios")** — Parse-only tests cover at minimum: (a) nonstop Alaska-metal row, (b) 1-stop Alaska-metal row, (c) partner-marketed row (Cathay/JAL/Qatar), (d) sold-out / empty result page, (e) cross-midnight redeye with "+1" indicator. Live smoke marked `@pytest.mark.e2e` asserts the LAX→JFK 2026-06-14 path returns at least one row OR raises `ProviderError` cleanly (no AttributeError, no Playwright timeout uncaught).

- **R4 (origin: parent plan U4 acceptance verification)** — `BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... uv run autopoints search LAX JFK 2026-06-14 --cabin economy --live-alaska --arrive-before 08:00ET` prints a ranked table where Alaska rows are present (or absent with a warning explaining why) AND the `--arrive-before` filter fires against Alaska's `arrival_time` (any redeye row arriving < 08:00 ET on 6/15 is kept; later rows are dropped per the U5 cross-TZ filter math from the PR #4 plan).

- **R5 (origin: v0 brainstorm Phase 2 "Direct provider expansion")** — `--live-alaska` help-text update: drop the "v0: provider skeleton" caveat once the implementation lands. Class docstring on `AlaskaProvider` updated to describe the actual scraper, not the stub. Existing v0 wiring tests (`test_provider_metadata`, `test_build_orchestrator_includes_alaska_when_flag_set`, etc.) keep passing.

Explicit non-goals (descope guardrails — defer all to follow-up):
- BrowserbaseAwardProvider shared base class (still premature with 1 consumer; revisit at 2-3).
- JetBlue / AA / Delta direct providers.
- A second proxy geo strategy (US-only for now).
- Persistent Browserbase session re-use across orchestrator fan-out (per-call session is fine at v1.a volume).
- Live balance fetch from Alaska's logged-in surface.
- Award-search calendar mode (multi-date sweep within a single Alaska session) — every search builds its own session.

## Key Technical Decisions

1. **Browserbase + Playwright (hand-rolled), not Stagehand.** Same call as the parent plan U4 KTD: Stagehand is reserved for AA/Delta in phase 2 where anti-bot (PerimeterX/Akamai) is the qualifying signal. Alaska's homepage loads cleanly under residential proxy + `solveCaptchas: True`; the v0 brainstorm probe confirmed this. Stagehand would add a dependency layer for no incremental capability against Alaska.

2. **Per-provider `Semaphore(1)` to bound concurrency.** Already in the v0 skeleton (`self._search_semaphore = asyncio.Semaphore(1)` in `AlaskaProvider.__init__`). Each Browserbase session is expensive and the orchestrator's date-window fan-out would otherwise spawn 3-5 simultaneous sessions per provider. The semaphore caps Alaska's own concurrency to 1 at-a-time. A *global* Browserbase semaphore (across providers) is a phase-2 follow-up, gated on second direct provider landing.

3. **Selector-discovery is a one-off interactive task.** `scripts/spike_alaska.py` is **NOT committed**. The discovered selectors live in `docs/probes/alaska-selectors.md` (which IS committed) and are encoded directly into `AlaskaProvider`. Rationale: the script's value is the empirical observations it produces, not the code path itself; committing it implies maintenance + CI obligations we don't want. Pattern matches `docs/probes/v1c-aeroplan-endpoint-discovery.md` — observations live in docs/, exploration scripts don't.

4. **Cabin mapping: `economy → Y`, `premium_economy → PE`, `business → J`, `first → F`.** Alaska's UI uses these single/double-letter labels in the cabin selector dropdown (per the v0 brainstorm probe screenshots). Encoded as a class-level constant `_CABIN_LABELS: Mapping[Cabin, str]` to keep the mapping centralized; the `search()` method translates the `Cabin` enum value into the click target.

5. **Partner vs. Alaska-metal distinction in result rows.** `AwardOffer.operating_carrier` is the *actual* flying airline IATA — for an Alaska-metal LAX-SEA segment it's `"AS"`; for a Cathay JFK-HKG redemption booked via Alaska it's `"CX"`. The `provider` field stays `"AS"` (the loyalty program issuing the award). When the UI exposes a marketing-vs.-operating distinction (e.g. a "Marketed by Alaska, operated by Hawaiian" tag), capture the *operating* carrier in `operating_carrier` and put any marketing/partner annotation in `fare_class` (or as a `notes`-style string on the AwardOffer if the schema needs it — TBD during U2, but `fare_class` is the first-pass home).

6. **Selectors are observed against the live render, not source-inspected.** Web Components are largely opaque to source view (the `borealis-expanded-booking-widget` is a custom element with shadow DOM); the spike works from `page.evaluate("document.activeElement")` + Playwright's `get_by_role`/`get_by_label` codegen + DevTools inspection at the *rendered* state. Observed `data-testid` attributes are preferred over CSS class names (more stable). If a particular control has no `data-testid`, fall back to ARIA role + accessible name.

7. **`dest_tz` is resolved via a small airport→IANA lookup, not scraped from the page.** Alaska's UI shows local times but no IANA tz label on result rows. A 200-line `airport_tz.py` (or even an in-method dict for the IATA codes we care about: NYC airports, SEA, LAX, SFO, HKG, NRT, DOH, etc.) is sufficient for v1.a. The lookup file is added in U2; expansion to full coverage is deferred.

8. **Single Browserbase session per `search()` call, closed in `finally`.** No session pooling. The v0 brainstorm explicitly accepted the "per-call session" cost — at v1.a request volume (single-digit daily searches against Alaska), this is well within the Developer-tier 25-concurrent quota. Pooling is phase-2 follow-up once watchlist runner usage is real.

## Output Structure

This plan touches one existing module, adds one tiny module (airport TZ lookup), one doc, and one test file diff. No new directory hierarchy.

```text
autopoints/
├── providers/
│   ├── alaska.py            # MODIFIED — search() body, class docstring, _CABIN_LABELS, _parse_results
│   ├── _airport_tz.py       # NEW — minimal IATA → IANA dict (10-20 codes for v1.a)
│   ├── _browserbase.py      # unchanged (already shipped in v0 U4)
│   └── base.py              # unchanged
├── cli/
│   └── main.py              # MODIFIED — drop "v0: provider skeleton" caveat from --live-alaska help text
└── search/
    └── build.py             # unchanged (already wires AlaskaProvider behind use_live_alaska)

docs/
├── plans/
│   └── 2026-06-08-001-feat-alaska-selector-spike-plan.md   # this file
└── probes/
    └── alaska-selectors.md  # NEW — captured selectors + result-row structure from spike

scripts/
└── spike_alaska.py          # NEW but UNCOMMITTED — one-off interactive script

tests/
├── test_alaska.py           # MODIFIED — add parse-only fixtures + e2e-marked live smoke
└── fixtures/
    └── alaska/              # NEW — HTML fixtures of various result-page states
        ├── nonstop.html
        ├── one_stop.html
        ├── partner_marketed.html
        ├── sold_out.html
        └── redeye_plus_one.html
```

The existing v0 wiring (`autopoints/search/build.py` registration, `autopoints/cli/main.py` flag, `autopoints/watchlist_runner.py` threading) requires no changes — they already gate on `use_live_alaska` and pass it through. Only the provider body and the help-text caveat change.

---

## Implementation Units

### U1. Selector-discovery spike

**Goal:** Drive Alaska's homepage award search for LAX → JFK on a near-term date against a live Browserbase session. Capture every selector + result-row structure detail needed for U2's encoding. Record observations in `docs/probes/alaska-selectors.md`. The spike script itself stays uncommitted.

**Requirements:** R1

**Dependencies:** none — first unit; blocks U2.

**Files:**
- `scripts/spike_alaska.py` (new, NOT committed) — interactive script the implementer runs locally with `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` set
- `docs/probes/alaska-selectors.md` (new, committed) — the artifact

**Approach:**
1. Script bootstraps a Browserbase session via `_browserbase.get_session()`. Navigates to `https://www.alaskaair.com/`. Pauses with `await page.pause()` so the implementer can inspect with DevTools.
2. Manually walk the booking widget flow in the open browser: click "One way", click "Use points" toggle, type "LAX" in From, accept the autocomplete, type "JFK" in To, accept, set a near-term date, click Search. Note every selector that worked.
3. Once on the results page, inspect a known good Alaska-metal row, a 1-stop row, a partner-marketed row (Cathay JFK-HKG on a date that has award space is a good check), and an empty/sold-out date.
4. Record in `docs/probes/alaska-selectors.md`:
   - **Form selectors:** From/To comboboxes, date input, One-way radio, Use-points toggle, Cabin selector, Search button. Prefer `data-testid` attrs; ARIA role + accessible name as fallback.
   - **Results selectors:** results container, result-row, points cell, taxes cell, depart time, arrive time, "+1 day" indicator, partner-marketed indicator, operating-carrier IATA, fare-class indicator, stops indicator.
   - **Page-state selectors:** loading spinner, "no flights found" empty state, error banner.
   - **Sample row HTML:** copy the outer HTML of one Alaska-metal row and one partner row into the doc as ground-truth snapshots — these double as fixture seeds for U3.
   - **Form-driving quirks:** the typeahead delay needed (`press_sequentially` `delay=` value), date-picker keystrokes (does it accept typed dates or require click?), redirect URL pattern after Search (`**/shopping/**` per the v0 plan's guess, but verify).
5. Capture 2-3 cross-route fixtures (LAX-JFK domestic, JFK-HKG via Cathay partner) so U3 has variety. Save the page HTML via `page.content()` to `tests/fixtures/alaska/*.html` files (U3 imports these directly).

**Patterns to follow:**
- `docs/probes/v1c-aeroplan-endpoint-discovery.md` shape: short narrative + bullet selector list + sample snippets. Markdown headings for each section.
- Implementer-facing tone — the doc is for the next implementer (possibly future-you) not for users.
- Use `await page.pause()` liberally for interactive inspection. The spike is *not* meant to be re-runnable end-to-end in headless mode; it's an interactive instrument.

**Test scenarios:**
- None — this is the empirical spike, output is the doc. The doc itself is reviewed by the implementer for completeness before declaring U1 done.

**Verification:**
1. `docs/probes/alaska-selectors.md` exists and contains: at minimum one selector entry per the bullet list in step 4, two sample row HTML snippets, a captured form-driving quirks section.
2. `tests/fixtures/alaska/nonstop.html`, `one_stop.html`, `partner_marketed.html`, `sold_out.html`, and `redeye_plus_one.html` exist (any non-empty content suffices; U3 asserts on their parsed shape).
3. Implementer can hand-walk the recorded selectors through Playwright's selector syntax mentally — no obviously-flaky CSS class chains, no nth-child indices.

---

### U2. Encode selectors into `AlaskaProvider.search()`

**Goal:** Replace the `ProviderError` stub in `AlaskaProvider.search()` with the real form-driving + result-parsing implementation. `AwardOffer` rows are populated end-to-end including `departure_time`, `arrival_time`, `arrival_date` (with "+1 day" handled), `dest_tz`, `operating_carrier`, and `fare_class`.

**Requirements:** R2, R5

**Dependencies:** U1 — needs the selector inventory from `docs/probes/alaska-selectors.md`.

**Files:**
- `autopoints/providers/alaska.py` (modify) — gut the `ProviderError` raise, implement `search()` and helper methods
- `autopoints/providers/_airport_tz.py` (new) — minimal IATA → IANA mapping dict for the v1.a airport set
- `autopoints/cli/main.py` (modify) — drop "v0: provider skeleton — raises ProviderError until selector-discovery spike lands (see plan U4)" caveat from the `--live-alaska` help text; replace with a steady-state description

**Approach:**
1. **Module-level structure** in `alaska.py`:
   - Add `_CABIN_LABELS: Mapping[Cabin, str] = {Cabin.economy: "Y", Cabin.premium_economy: "PE", Cabin.business: "J", Cabin.first: "F"}` near the top. Use Alaska's actual UI labels as recorded in U1 (may diverge slightly — adjust during U2 if so).
   - Add `_HOMEPAGE_URL = "https://www.alaskaair.com/"` as a module constant.
   - Add `_PAGE_LOAD_TIMEOUT_MS = 15000` and `_RESULTS_TIMEOUT_MS = 30000` as module constants matching the parent plan U4 error-handling spec.
2. **`search()` body** structure:
   ```
   async with self._search_semaphore:
       page, browser = await get_session()
       try:
           await self._drive_form(page, origin, destination, depart_date, cabin, passengers)
           html = await self._wait_for_results(page)
           return self._parse_results(html, origin, destination, depart_date, cabin)
       except PlaywrightTimeoutError as e:
           raise ProviderError(f"alaska: UI did not respond in time ({e})") from e
       except ProviderError:
           raise
       except Exception as e:
           raise ProviderError(f"alaska: unexpected error during search ({e!r})") from e
       finally:
           await browser.close()
   ```
3. **`_drive_form(page, ...)`** — translates the U1 selector inventory into a Playwright sequence. Sequence per parent plan U4 step 2:
   - `await page.goto(_HOMEPAGE_URL, wait_until="domcontentloaded")`
   - `await page.wait_for_selector(<booking widget host selector>, timeout=_PAGE_LOAD_TIMEOUT_MS)`
   - Click One-way radio, click Use-points toggle.
   - Click From combobox, `press_sequentially(origin, delay=80)`, wait for option list, click first option whose text contains `origin`.
   - Same for destination.
   - Click date input, type `depart_date.strftime("%m/%d/%Y")` (or whatever format U1 recorded), press Enter then Escape to close the picker if it sticks open.
   - If cabin != economy: open the cabin selector, click the option whose label matches `_CABIN_LABELS[cabin]`.
   - Set passenger count (U1 should record where this lives — may be a stepper).
   - Click Search.
4. **`_wait_for_results(page)`** — `await page.wait_for_url("**/shopping/**", timeout=_RESULTS_TIMEOUT_MS)` per the parent plan's guess; if U1 recorded a different post-search URL pattern, adjust. Also wait for a results-container selector. Return `await page.content()`.
5. **`_parse_results(html, origin, destination, depart_date, cabin)`** — pure function (no Playwright) taking HTML string + the search context. Parses via `selectolax` (already a dep) or `BeautifulSoup` (whichever is already pulled in by another provider — match the existing convention). For each result row:
   - Extract operating carrier (IATA from a logo/text element).
   - Extract points (int after stripping commas).
   - Extract taxes (int cents — multiply parsed USD by 100).
   - Extract departure-time string (e.g. "10:25 PM") → `time` via `datetime.strptime("%I:%M %p")`.
   - Extract arrival-time string the same way.
   - Detect "+1" indicator next to arrival time → `arrival_date = depart_date + timedelta(days=1)`; else `arrival_date = depart_date`.
   - Extract fare class if shown (Alaska shows e.g. "Saver" / "Main" labels — record in `fare_class`).
   - Detect partner-marketed: if the operating carrier IATA differs from `"AS"`, treat as partner; the partner-ness is implicit in `operating_carrier`. If the UI surfaces an explicit "Operated by X" string, that's the more reliable signal.
   - Build `AwardOffer(provider="AS", operating_carrier=op_iata, origin=origin, destination=destination, depart_date=depart_date, cabin=cabin, points=pts, taxes_cents=tax_cents, fare_class=fc, stops=stops, departure_time=dep_t, arrival_time=arr_t, arrival_date=arr_d, dest_tz=AIRPORT_TZ.get(destination, "America/New_York"))`.
   - Skip the row (don't raise) if parsing of an essential field (points, depart/arrive time) fails — emit nothing for that row. Defensive parsing pattern from `amadeus.py` / `google_flights.py`.
6. **`_airport_tz.py`** content — a flat `AIRPORT_TZ: dict[str, str]` covering the airports a user is realistically going to query Alaska for in v1.a:
   - US: LAX, SFO, SEA, PDX, ANC, SJC, SAN, LAS, PHX, DEN, ORD, MDW, JFK, LGA, EWR, BOS, IAD, DCA, MIA, FLL, ATL, DTW, MSP, DFW, HOU, IAH, MCO.
   - Asia (partner routes): HKG (Cathay), NRT, HND (JAL), ICN (KE — though Alaska dropped KE; keep for future).
   - Middle East: DOH (Qatar).
   - Europe: LHR (BA — though Alaska Atmos partner status varies; keep the airport entry, drop the partner if Atmos no longer redeems on BA).
   - Default fallback when the destination isn't in the dict: `"America/New_York"` (yields a slightly wrong filter for unmapped destinations but doesn't crash — accepted trade-off; document in module docstring).
7. **CLI help text update** in `cli/main.py`:
   ```
   "Include Alaska Mileage Plan (Atmos Rewards) live award search. "
   "Requires BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID in .env. "
   "Searches Alaska-metal and partner-marketed (Cathay, JAL, Qatar) award space."
   ```
   Drop the "v0: provider skeleton" caveat.
8. **Class docstring update** in `alaska.py`: replace the v0 stub docstring with the steady-state description matching the actual implementation. Note the residential-proxy + `solveCaptchas` posture, the per-provider Semaphore(1), the partner-vs.-metal convention in `operating_carrier`.

**Patterns to follow:**
- Provider `search()` signature comes from `AwardProvider` (already inherited). Don't change the protocol.
- `from __future__ import annotations` at module top — already there from the v0 skeleton.
- mypy-strict full return annotations on every method — already required by `pyproject.toml`.
- Defensive parsing per `amadeus.py` / `google_flights.py` — skip malformed rows, don't blow up the whole search.
- Browserbase session lifecycle: `try/finally browser.close()` — matches the `_browserbase.get_session` docstring contract that the caller closes the browser.
- `PlaywrightTimeoutError` import: `from playwright.async_api import TimeoutError as PlaywrightTimeoutError` per Playwright Python convention.

**Test scenarios:**
- *Implementation-time only (covered by U3):* unit-level fixture-driven assertions on `_parse_results`. U2 itself is exercise-by-running via the CLI; U3 codifies the assertions.

**Verification:**
1. `uv run autopoints search LAX JFK 2026-06-14 --cabin economy --live-alaska` (with Browserbase env vars set) prints at least one `AS` row OR a warning saying "no award space" (verified by manual check on alaskaair.com — both outcomes are valid; what's NOT valid is an uncaught exception or the v0 stub message).
2. Class docstring on `AlaskaProvider` no longer says "skeleton" or "stub" or "pending".
3. `autopoints search --help` shows the updated `--live-alaska` text without the "v0: provider skeleton" caveat.
4. `uv run mypy autopoints/providers/alaska.py` clean.
5. `uv run ruff check autopoints/providers/alaska.py` clean.

---

### U3. Parse-only fixture tests + `@pytest.mark.e2e` live smoke

**Goal:** Lock the parser shape with HTML fixtures captured during U1 so future Alaska UI changes surface as test failures, not silent breakage. Add a `@pytest.mark.e2e` live smoke that asserts the LAX-JFK round-trip path works end-to-end against a real Browserbase session.

**Requirements:** R3

**Dependencies:** U2 (parser exists), U1 (fixture HTML captured).

**Files:**
- `tests/test_alaska.py` (modify) — keep all existing v0 wiring tests untouched; append the new parse-only block + the e2e smoke
- `tests/fixtures/alaska/*.html` (existing from U1) — referenced by the parse-only tests

**Approach:**
1. Add module-level fixture loader:
   ```python
   FIXTURES_DIR = Path(__file__).parent / "fixtures" / "alaska"

   def _load(name: str) -> str:
       return (FIXTURES_DIR / name).read_text(encoding="utf-8")
   ```
2. **Parse-only tests** (no Browserbase, no Playwright — purely on `_parse_results`):
   - `test_parse_nonstop_alaska_metal`: loads `nonstop.html`, asserts `len(offers) >= 1`, asserts the first row has `provider == "AS"`, `operating_carrier == "AS"`, `points` > 0, `departure_time` is not None, `arrival_time` is not None, `arrival_date == depart_date`, `stops == 0`.
   - `test_parse_one_stop_alaska_metal`: loads `one_stop.html`, asserts at least one row has `stops == 1`.
   - `test_parse_partner_marketed_cathay`: loads `partner_marketed.html`, asserts at least one row has `operating_carrier != "AS"` (likely `"CX"` for Cathay), `points` > 0, `provider == "AS"` (still issued by Alaska).
   - `test_parse_sold_out`: loads `sold_out.html`, asserts `_parse_results(...) == []` (no rows, no exception).
   - `test_parse_redeye_plus_one`: loads `redeye_plus_one.html`, asserts at least one row has `arrival_date == depart_date + timedelta(days=1)` (the "+1" indicator was honored).
   - `test_parse_skips_malformed_row`: synthesize a minimal HTML string with one valid row and one row missing the points cell, assert the parser returns the valid row only (length 1, no exception).
3. **Live smoke** (marked `@pytest.mark.e2e`):
   - `@pytest.mark.e2e` `test_live_smoke_lax_jfk` — pulls env vars, skips with `pytest.skip(...)` if either is missing. Calls `await AlaskaProvider().search("LAX", "JFK", date(2026, 6, 14), Cabin.economy)`. Asserts the call either returns a `list[AwardOffer]` (possibly empty if Alaska's sold out) OR raises `ProviderError` (e.g. Browserbase 429). What it must NOT do: raise `AttributeError`, `KeyError`, `PlaywrightTimeoutError` uncaught.
   - Add `e2e` marker to `pyproject.toml` `[tool.pytest.ini_options].markers` if not already present.
4. Keep all existing v0 wiring tests untouched: `test_provider_metadata`, `test_search_raises_provider_error_with_actionable_message`, `test_per_provider_semaphore_serializes_concurrent_calls`, `test_build_orchestrator_includes_alaska_when_flag_set`, `test_build_orchestrator_omits_alaska_by_default`, `test_orchestrator_surfaces_alaska_stub_as_warning`.
   - **The `test_search_raises_provider_error_with_actionable_message` test needs an update** — its assertion is `"selector-discovery spike" in msg`, which no longer holds after U2. Update it to assert the search either returns a `list[AwardOffer]` or raises a `ProviderError` for a non-Browserbase reason (e.g. by stubbing `_browserbase.get_session` to raise). Same goes for `test_per_provider_semaphore_serializes_concurrent_calls` and `test_orchestrator_surfaces_alaska_stub_as_warning` — rewrite so they exercise a deterministic failure mode (Browserbase env vars unset) rather than the stub message.

**Patterns to follow:**
- Pytest fixtures via `Path(__file__).parent / ...` pattern — repo convention.
- `@pytest.mark.e2e` marker: same convention used elsewhere in the suite for tests that hit external services. Default test run (`pytest -q`) skips them via `-m "not e2e"` in the project's pytest config (or via a CI gating mechanism — verify in `pyproject.toml`).
- Skip-when-creds-missing pattern: `if not os.environ.get("BROWSERBASE_API_KEY"): pytest.skip("Browserbase creds not set")`.

**Test scenarios:**
- Listed in the Approach section above (1 parse-only suite of 6 tests + 1 e2e smoke).
- All 6 v0 wiring tests adjusted to still apply after U2.

**Verification:**
1. `uv run pytest tests/test_alaska.py -q` passes all parse-only + adjusted v0 wiring tests. e2e is skipped (no env vars) or run+passes (env vars set).
2. `uv run pytest -q -m "not e2e"` (full default suite) passes — 87 v0 baseline + new parse tests, no regressions.
3. `uv run pytest -q -m e2e` (CI gate or local run with creds) executes the live smoke without uncaught exceptions.

---

### U4. Wire end-to-end (CLI `--live-alaska`, ranked table, help text update)

**Goal:** Confirm the end-to-end path works at the CLI level — `--live-alaska` flag includes Alaska in the search, the ranked table renders Alaska rows correctly (including partner-marketed rows visually distinguishable from chart-floor rows), and the `--arrive-before` filter fires against Alaska's `arrival_time`. Update CLI help text and class docstring (overlaps slightly with U2's text changes — verified here in context).

**Requirements:** R4, R5

**Dependencies:** U2 (provider works), U3 (parser shape locked).

**Files:**
- `autopoints/cli/main.py` (modify, possibly already done in U2) — final pass on the `--live-alaska` help text; ensure the rendered table includes a column or visual indicator that surfaces `operating_carrier` for partner rows (verify against existing `_render(outcome)` — may already do this if the v0 table renders `award_offer.operating_carrier`)
- `autopoints/providers/alaska.py` (modify, already done in U2) — final docstring pass
- No new files

**Approach:**
1. Walk the CLI end-to-end manually:
   ```
   BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... uv run autopoints search LAX JFK 2026-06-14 --cabin economy --live-alaska
   ```
   - Confirm at least one row with `program=AS` appears (or the warning explains absence).
   - Confirm `arrival_time` is populated on Alaska rows.
   - Confirm partner-marketed rows (if any on this route) show the operating carrier somewhere in the table — check what `_render(outcome)` does today with `operating_carrier`; if it's omitted, add it as a column or include it in the carrier field.
2. Re-run with `--arrive-before 08:00ET`:
   ```
   ... --live-alaska --arrive-before 08:00ET
   ```
   - Confirm the filter fires: rows with `arrival_time` past 08:00 ET on 2026-06-15 are dropped. Cross-check by re-running without the filter and noting which rows disappear.
3. Confirm the chart-floor providers (AC, BA, VS) still ship rows that pass the filter (they have no `arrival_time` — must pass through per the U5 filter logic in the PR #4 plan).
4. Run with both flags off (default state) — confirm no Alaska rows appear (regression check).
5. Help text: `autopoints search --help | grep -A2 live-alaska` — verify the message no longer says "v0: provider skeleton".
6. Re-verify `autopoints/search/build.py` — should require no changes (already wires `AlaskaProvider()` behind `opts.use_live_alaska`). Read it once to confirm.
7. Re-verify `autopoints/watchlist_runner.py` — should require no changes (already threads `use_live_alaska` through). Read it once to confirm.

**Patterns to follow:**
- The `_render(outcome)` function in `cli/main.py` controls the table — match its existing Rich column layout when adding/exposing `operating_carrier`.
- If a column already shows operating carrier (likely — check before adding), no code change is needed and U4 is purely verification.

**Test scenarios:**
- *Manual verification scenarios* (above).
- *Automated:* full suite (`uv run pytest -q -m "not e2e"`) still green — no regressions from the U2/U3 changes leaking into other tests.

**Verification:**
1. Acceptance command from R4 prints a non-empty ranked table where Alaska rows appear with populated `arrival_time`.
2. Adding `--arrive-before 08:00ET` to the same command yields a strictly shorter table (or same length if all rows already qualified) — confirms the filter fires.
3. `autopoints/cli/main.py` final state matches the steady-state help text from U2.
4. Full default-marker suite passes: `uv run pytest -q -m "not e2e"` returns 0.
5. Smoke: `uv run autopoints search LAX JFK 2026-06-14 --cabin economy` (NO `--live-alaska`) — confirms no Alaska rows appear in the default state (regression guard).

---

## Risks & Dependencies

| Risk | Mitigation |
|---|---|
| Alaska UI changes between U1 spike and U2 encoding (small window but possible) | U3's parse-only fixtures use HTML captured during U1; U2's parser depends on `docs/probes/alaska-selectors.md` not the live page. UI drift surfaces as a parse-test failure in CI, not a silent breakage. |
| Browserbase session creation flaky under load / 429 from quota | `_browserbase.get_session()` raises `ProviderError` which the orchestrator already surfaces as a warning. Provider doesn't crash the full search; user sees "alaska: Browserbase 429 — try again" and Alaska rows are absent but other providers still ship. |
| Partner-marketed row format differs significantly from Alaska-metal row format (column shifts, extra annotations) | U1 explicitly captures *both* row types as fixtures. U3 has separate `test_parse_partner_marketed_cathay` test. If U1 reveals the rows are structurally different enough that one parser can't handle both, split `_parse_results` into `_parse_alaska_row` + `_parse_partner_row` with a dispatch step — note this as a U2-time decision. |
| Cabin label mapping (`Y`/`PE`/`J`/`F`) doesn't match Alaska's actual UI labels | KTD #4 calls this out — `_CABIN_LABELS` is centralized so the implementer can adjust during U2 based on what the U1 spike actually saw. Worst case: labels are spelled-out ("Economy", "Business") and the mapping changes; structurally identical to the planned shape. |
| Per-call Browserbase session cost stacks up for orchestrator's date-window fan-out (e.g. `--window 3` × LAX-JFK × Alaska = 7 sessions) | Per-provider `Semaphore(1)` serializes (acceptable latency hit for v1.a). Phase-2 work: persistent session re-use across a single orchestrator run if cost becomes a blocker. |
| `dest_tz` lookup misses an airport, falls back to ET, causes `--arrive-before` math to be off | KTD #7: minimal lookup with ET fallback is intentional for v1.a. Add airports as we encounter them in real searches; expansion to full IATA coverage is deferred. |
| AwardWiz's archived flow uses CDP directly (Arkalis), not Playwright — patterns may not map 1:1 | AwardWiz is a *reference*, not a blueprint. The form-driving sequence (One-way → Use-points → From → To → Date → Search) is universal; the exact CDP commands vs. Playwright API calls differ but the user-facing sequence is what we're cribbing. Document where AwardWiz informed a decision in code comments only — no direct port. |
| Spike implementer captures incomplete selector inventory in U1, U2 hits unknowns and stalls | U1's verification step explicitly enumerates every selector the implementer must record; the doc is reviewed-by-self before declaring U1 done. If U2 hits an unknown, fold back to U1 with a short addendum to `docs/probes/alaska-selectors.md` rather than guessing. |

## Deferred to Follow-Up Work

- BrowserbaseAwardProvider shared base class (still 1 consumer; revisit at 2-3).
- JetBlue / AA / Delta direct providers (gated on Stagehand probe, separate plan).
- Persistent Browserbase session re-use across orchestrator date-window fan-out.
- Calendar-mode Alaska search (multi-date sweep within one session) — single-date per session for v1.a.
- Full IATA → IANA `dest_tz` coverage (v1.a covers ~20 airports relevant to Alaska routes).
- Award-search confidence score on partner rows (some partners have known-stale UI lag).
- Live Alaska balance fetch from logged-in surface (separate auth flow, deferred).
- Stale-availability re-verifier (cross-references Alaska's quoted points against the chart floor; phase-2).
- Linux-Docker Browserbase credential storage strategy (already deferred from v0 plan).
- Global Browserbase semaphore across providers (gated on 2nd direct provider landing).
- A specific `PartnerAwardOffer` schema variant if `operating_carrier` + `fare_class` prove insufficient to capture the partner distinction (defer until proven needed).

## Sources & Research

- **Parent plan** — `docs/plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md` U4 ("Alaska direct award provider via Browserbase + Playwright"). Records the Approach, Patterns to follow, and Execution note that this plan finishes.
- **v0 brainstorm** — `docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md` "Direct provider (1)" + Phase 2 section. Records the partner sweet-spot value prop (Cathay JFK-HKG F 70k, JAL longhaul J ~60k, Qatar QSuite ~70k).
- **v0 brainstorm probe** — alaskaair.com homepage cold load confirmed: booking widget renders, "Use points" toggle present, Web Component-based (`auro-formkit`, `planbook-radio-group`, `borealis-expanded-booking-widget`), no URL-driven prefill (form-driving required).
- **AwardWiz** (archived Sep 2024) — https://github.com/lg/awardwiz. Alaska scraper used custom CDP engine "Arkalis". Reference for form sequence (One-way → Use-points → From/To → Date → Search), not for code. Archived status means we can't expect upstream patches.
- **`flightplan-tool/flightplan`** (unmaintained) — referenced in parent plan U4 Sources; confirms no public JSON XHR endpoint exists for Alaska award search. Form-driving via headless browser is the only path.
- **Alaska Atmos Rewards rebrand** (August 2025) — program name change from "Mileage Plan" to "Atmos Rewards". User-facing branding only; award charts and partner relationships unchanged at rebrand. URL `alaskaair.com` and account login surface unchanged.
- **Browserbase Python SDK docs** — https://docs.browserbase.com/reference/sdk/python. `sessions.create(project_id, proxies, browser_settings={"solveCaptchas": True})` shape; residential proxy with `geolocation.country = "US"`. Same as parent plan U4.
- **Playwright async Python API** — https://playwright.dev/python/docs/api/class-page. `press_sequentially(text, delay=N)` for typeahead, `wait_for_url(**/shopping/**)` for post-search navigation, `wait_for_selector` with explicit timeout. Same as parent plan U4.
- **PR #3** (v0 ship) and **PR #4** (post-review residuals) — establish the surrounding state: filter logic, watchlist runner, cross-TZ math that this plan's `arrival_time` populations must feed correctly.

## Acceptance: Outcome the plan must enable

After all four units land:

```text
BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... \
  uv run autopoints search LAX JFK 2026-06-14 \
  --cabin economy --live-alaska --arrive-before 08:00ET
```

returns a ranked list combining:
- Live cash baseline from Google Flights (existing, unchanged from v0).
- **Live Alaska Mileage Plan / Atmos Rewards award availability** for the same date — including any Cathay/JAL/Qatar partner sweet spots Alaska has loaded for the route — with `arrival_time` populated so the `--arrive-before` filter actually drops late-arriving Alaska rows (not just chart-floor pass-throughs).
- Chart-floor pricing for AC / BA / VS (existing, unchanged).
- Visual distinction in the rendered table between Alaska-metal rows (`operating_carrier=AS`) and partner-marketed rows (`operating_carrier in {CX, JL, QR, ...}`).

Plus:
- `--live-alaska` help text no longer says "v0: provider skeleton".
- `tests/test_alaska.py` has parse-only fixtures + e2e-marked live smoke; full default suite (`pytest -q -m "not e2e"`) is green.
- `docs/probes/alaska-selectors.md` exists as the documentation artifact of the spike, ready for the next implementer if Alaska's UI shifts and selectors need re-validation.
- `scripts/spike_alaska.py` is NOT in the repo (gitignored or simply never added) — its purpose was the doc, not the script.
