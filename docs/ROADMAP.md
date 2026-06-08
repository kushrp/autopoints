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

**Goal:** Replace the v0 Alaska skeleton with a real live scraper; port `timrogers/ba_rewards` iOS API for BA Avios; either repair the broken Aeroplan endpoint or formally retire the live provider.

**Plan:** TBD per sub-milestone (each sub-PR scopes its own plan in `docs/plans/`).

**Acceptance (one-line per sub-milestone — specific gates live in each sub-plan):**

- **v1.a Alaska real implementation** — `AlaskaProvider.search` returns at least one bookable `AwardOffer` with populated time-of-day fields for a known-available partner-award route. Replaces the v0 skeleton; `--live-alaska` exercises the live path end-to-end.
- **v1.b BA Avios iOS API port** — `BritishAirwaysProvider` (ported from `timrogers/ba_rewards`) returns Avios + taxes for a known route, matching public ba.com display. Pure HTTP — no new browser deps.
- **v1.c Aeroplan endpoint repair** 🟡 **in progress** — endpoint identified at `akamai-gw.dbaas.aircanada.com/loyalty/dapidynamicplus/...` (see `docs/probes/v1c-aeroplan-endpoint-discovery.md`). **v1.c-1 ✅ shipped (PR #6)**: Cognito + SigV4 + market-token handshake + ama-* headers + 10 respx-mocked tests. **v1.c-2 scaffolded**: `AeroplanProvider(use_browserbase=True)` extension point in place; full Kasada bypass via Browserbase Chrome session is the remaining work. **v1.c-1.5 pending — refresh Cognito IdentityId**: AC revoked the hardcoded value; live-checks harness reports 403 "explicit deny in identity-based policy" from the market-token layer. Fresh capture instructions in [`docs/probes/v1c-aeroplan-identity-refresh.md`](probes/v1c-aeroplan-identity-refresh.md) — ~15 min via Chrome DevTools.

**v1 done when:** all three sub-PRs merge. Each can ship independently.

---

## v1.5 — AA / Delta direct (gated on Stagehand probe)

**Conditional milestone.** The 30-minute Stagehand probe (task #30) must succeed first. If it fails, this milestone stays deferred indefinitely per STRATEGY's documented revert path.

**Gate:** Run `scripts/probe_stagehand.py` (uncommitted) against `aa.com` (PerimeterX) and `delta.com` (Akamai). Record pass/fail in `docs/probes/v15-stagehand-feasibility-research.md`. If the probe passes, scope v1.5 with a dedicated plan.

**Acceptance:** scope only after probe passes — gates land with the plan.

---

## v2 — Watchlist polish + multi-surface parity

**Goal:** Make the autonomous-background experience durable. Surface `--arrive-before` / `--live-alaska` through FastAPI and Discord. Add an MCP server. Build the stale-availability re-verifier flagged in STRATEGY.

**Plan:** TBD when scoped.

**Acceptance:** scoped per-component when planned — major themes are multi-surface parity (FastAPI/Discord/MCP), stale-availability re-verification, global Browserbase concurrency cap, credential storage on the Linux NAS target, and one watchlist running autonomously for a week without manual intervention.

---

## How to use this roadmap

1. Each milestone has explicit, demoable acceptance gates. Don't move on until the gates pass.
2. Plans (in `docs/plans/`) hold the per-unit implementation detail. The roadmap holds the *user-facing outcome* gates.
3. Status mark — `✅ done`, `🟡 in progress`, blank — at the top of each section. Update as you ship.
4. PR descriptions should reference the milestone gate they unblock so the PR check + the milestone gate are clearly tied.
5. If a gate keeps failing for 2+ PR rounds, revisit the milestone scope. A gate that doesn't fail occasionally probably isn't testing the right thing.
