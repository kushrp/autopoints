# Roadmap

Sequenced milestones with explicit acceptance gates. **A milestone cannot start until the previous one's gates have passed** — this preserves the "test that it works before moving on" discipline.

The gates are the practical, demoable validation each milestone must clear before its label flips to `done`. They are not the same as the unit-level test scenarios inside each plan; those are necessary but not sufficient. The gates verify the milestone delivers the user-facing outcome it promised.

Strategy context: [`docs/STRATEGY.md`](STRATEGY.md). Each milestone references the plan and PR that delivered it.

---

## v0 — Foundational sprint ✅ done (2026-06-08)

**Goal:** Replace dying Amadeus with `fli` for Google Flights cash data; add time-of-day schema and a `--arrive-before` CLI filter; ship Alaska direct provider as a skeleton; deprecate the broken Aeroplan endpoint.

**Plan:** [`docs/plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md`](plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md)
**PR:** [#3](https://github.com/kushrp/autopoints/pull/3) — merged at 9db8437

**Acceptance gates (all passed):**
- [x] `autopoints search LAX JFK 2026-06-14` returns live Google Flights cash data with departure/arrival times populated
- [x] Schema migration on existing watchlists DB is idempotent (`PRAGMA table_info` guard)
- [x] 62 baseline tests still pass; ≥25 new tests added covering the 5 units
- [x] `autopoints --help` shows `--arrive-before HH:MM<TZ>` with the documented TZ aliases
- [x] CI green (test + e2e-browser) on the PR
- [x] Aeroplan provider opt-in flag remains default `False` with deprecation note in docstring + CLI help

---

## v0.1 — Post-review residuals (in progress)

**Goal:** Address the 5 deferred `ce-code-review` findings flagged from PR #3's "Residual Review Findings" section.

**Plan:** [`docs/plans/2026-06-07-002-fix-post-review-residuals-plan.md`](plans/2026-06-07-002-fix-post-review-residuals-plan.md)
**PR:** TBD (branch `feat/post-review-residuals`)

**Acceptance gates (must pass before starting v1):**
- [ ] Cross-TZ filter produces correct drop/keep decisions for a LAX→NRT scenario (`08:30 JST 10-16` drops, `20:30 JST 10-16` keeps when filter is `08:00ET`)
- [ ] `run_all` survives a single watchlist's failure — other watchlists complete; failing watchlist surfaces as a degraded `WatchlistRunResult` with `warnings` populated
- [ ] Parse-error warning text includes `arrive-before filter disabled, returning unfiltered results:`
- [ ] `GoogleFlightsProvider` logs via `logger.exception` on broad catch (verified by `caplog` test)
- [ ] **Forcing-function gate** — `autopoints search LAX JFK 2026-06-14 --arrive-before 08:00ET --demo` returns fewer rows than the unfiltered demo output, because chart-floor results whose cash baseline arrives after 08:00 ET 6/15 are now dropped
- [ ] 90+ tests pass (87 baseline from v0 + new scenarios)
- [ ] CI green on the v0.1 PR

---

## v1 — Live award providers

**Goal:** Replace the v0 Alaska skeleton with a real Browserbase + Playwright scraper; port `timrogers/ba_rewards` iOS API for BA Avios; either repair the Aeroplan endpoint or formally retire the live provider.

**Plan:** TBD (`docs/plans/2026-06-?-003-feat-live-award-providers-plan.md` once we scope it)
**PR(s):** likely 2–3 separate PRs gated by sub-acceptance:

1. **v1.a — Alaska real implementation**
   - [ ] Run `scripts/spike_alaska.py` (uncommitted) against a live Browserbase session and record the selector map in a one-time `docs/probes/alaska-selectors.md`
   - [ ] `AlaskaProvider.search` returns at least 1 `AwardOffer` for a known-available route (e.g., SEA→PVD 2026-09-15 saver economy) with `arrival_time`, `arrival_date`, `dest_tz` populated
   - [ ] `--live-alaska` from the CLI exercises the live path; results show in the ranked table with verdict
   - [ ] Browserbase session cost on a single search ≤ $0.05 (verified from dashboard) — if higher, revisit caching TTL
   - [ ] `@pytest.mark.e2e` test against a recorded HAR or live session

2. **v1.b — BA Avios iOS API port**
   - [ ] `BritishAirwaysProvider` ports the auth + JSON shape from `timrogers/ba_rewards`
   - [ ] Live Avios price + taxes for a known route (LHR→BCN 2026-09-15) matches what ba.com shows within ±500 Avios
   - [ ] No Browserbase usage (this is a pure HTTP path) — `pyproject.toml` doesn't add new browser deps
   - [ ] CI green; new unit tests with `respx` fixtures

3. **v1.c — Aeroplan endpoint repair or retire**
   - [ ] Determine current Air Canada award-search hostname; record finding in `docs/probes/aeroplan-endpoint.md`
   - [ ] Either: live AC search returns ≥ 1 result for a known route (passes); or: live provider is deleted, `--use-live-aeroplan` flag removed, AC chart-floor remains
   - [ ] If repaired: BA iOS pattern (no Browserbase, JSON shape) preferred over Browserbase

**v1 done when:** all three sub-acceptance lists pass. Each sub-PR can ship independently; the milestone closes when the last one merges.

---

## v1.5 — AA / Delta direct via Stagehand (gated)

**Goal:** Add AA and Delta as live award providers via Browserbase Stagehand. **This milestone is conditional** — the 30-minute Stagehand probe (task #30) must succeed first.

**Gate before starting:**
- [ ] Stagehand probe (`scripts/probe_stagehand.py`, uncommitted) runs against `aa.com` (PerimeterX) AND `delta.com` (Akamai) without bot blocks for ≥ 5 consecutive searches
- [ ] Probe output recorded in `docs/probes/stagehand-anti-bot.md` with pass/fail per site and notes on what bypassed defenses (if anything)
- [ ] If probe fails: v1.5 stays deferred indefinitely per STRATEGY revert path; document the failure and move to v2

**Plan:** TBD (only written if probe passes)

**Acceptance gates (only relevant if probe passed):**
- [ ] Stagehand-driven AA scraper returns ≥ 1 result for a known route (JFK→LHR 2026-10-15 saver economy) with full time-of-day fields
- [ ] Stagehand-driven Delta scraper returns ≥ 1 result for a known route (JFK→LAX 2026-09-30 main cabin)
- [ ] Per-search Anthropic/OpenAI token cost ≤ $0.20 each (verified)
- [ ] AA's MFA flow is either bypassed (pre-warmed Browserbase session) or out-of-scope (logged-out search returns useful data)

---

## v2 — Watchlist polish + multi-surface parity

**Goal:** Make the autonomous-background experience actually durable. Surface `--arrive-before` / `--live-alaska` through FastAPI and Discord. Add an MCP server. Build the stale-availability re-verifier flagged in STRATEGY.

**Plan:** TBD

**Acceptance gates:**
- [ ] FastAPI `SearchAPIRequest` and `WatchlistCreate` carry `arrive_before_local` field; Discord slash-commands have matching parameters
- [ ] MCP server (`autopoints/mcp/server.py`) exposes `search`, `add_watchlist`, `run_watchlists`, `list_balances` tools usable from Claude Code via stdio transport
- [ ] Stale-availability re-verifier: before a watchlist alert fires, the result is re-hit at the source; if it disappeared, the alert suppresses
- [ ] Global Browserbase semaphore caps concurrent sessions across all providers and watchlists (prevents the cost-blowout flagged in the v0.1 review)
- [ ] One watchlist runs autonomously on the NAS for 7 consecutive days; new-hit Discord pings fire only for genuinely new availability (false-positive rate ≤ 10% across the week)
- [ ] Keychain auth helper (or env-based equivalent for the Linux Docker target) stores Browserbase + airline credentials; live balance scrape for at least 1 program

---

## How to use this roadmap

1. Each milestone has explicit, demoable acceptance gates. Don't move on until the gates pass.
2. Plans (in `docs/plans/`) hold the per-unit implementation detail. The roadmap holds the *user-facing outcome* gates.
3. Status mark — `✅ done`, `🟡 in progress`, blank — at the top of each section. Update as you ship.
4. PR descriptions should reference the milestone gate they unblock so the PR check + the milestone gate are clearly tied.
5. If a gate keeps failing for 2+ PR rounds, revisit the milestone scope. A gate that doesn't fail occasionally probably isn't testing the right thing.
