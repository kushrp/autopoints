# Roadmap

Sequenced milestones with explicit acceptance gates. **A milestone cannot start until the previous one's gates have passed** — this preserves the "test that it works before moving on" discipline.

The gates are the practical, demoable validation each milestone must clear before its label flips to `done`. They are not the same as the unit-level test scenarios inside each plan; those are necessary but not sufficient. The gates verify the milestone delivers the user-facing outcome it promised.

Strategy context: [`docs/STRATEGY.md`](STRATEGY.md). Each milestone references the plan and PR that delivered it.

---

## v0 — Foundational sprint ✅ done (2026-06-07)

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

## v0.1 — Post-review residuals ✅ done (2026-06-08)

**Goal:** Address the 5 deferred `ce-code-review` findings flagged from PR #3's "Residual Review Findings" section.

**Plan:** [`docs/plans/2026-06-07-002-fix-post-review-residuals-plan.md`](plans/2026-06-07-002-fix-post-review-residuals-plan.md)
**PR:** [#4](https://github.com/kushrp/autopoints/pull/4)

**Acceptance gates (all passed):**
- [x] Cross-TZ filter produces correct drop/keep decisions for a LAX→NRT scenario
- [x] `run_all` survives a single watchlist's failure with degraded result + warnings
- [x] Parse-error warning text includes `arrive-before filter disabled, returning unfiltered results:`
- [x] `GoogleFlightsProvider` logs via `logger.exception` on broad catch
- [x] Forcing-function gate: `--arrive-before 08:00ET --demo` returns fewer rows than unfiltered
- [x] 90+ tests pass; CI green

---

## v1.b — MCP-pluggable CLI surface ✅ done (2026-06-08)

**Goal:** Finalize the CLI surface so that it doubles as the MCP tool surface. Real fixes from the doc-review pass.

**PR:** [#9](https://github.com/kushrp/autopoints/pull/9)

**Acceptance gates (all passed):**
- [x] `autopoints search LAX NYC 2026-06-13` fans out across JFK + LGA + EWR and returns one merged ranked table
- [x] `autopoints compare LAX,SFO NYC 2026-06-13,2026-06-14` produces a 12-combination matrix view
- [x] `autopoints search ... --json` emits a stable, MCP-consumable JSON document mirroring `SearchOutcome`
- [x] `GoogleFlightsProvider` auto-retries once on transient failure; flake rate halved in real use
- [x] Aeroplan auto-enables when `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` are configured; explicit `--no-live-aeroplan` opts out
- [x] 126 tests pass (112 baseline + 14 new for metros / --json / compare / retry / auto-detect)
- [x] CI green (test + e2e-browser)

---

## v1.c — Aeroplan endpoint repair ❌ invalidated (2026-06-08)

**Status:** Retired. Both shipped sub-milestones revealed the architecture itself is wrong, not the implementation.

- **v1.c-1** ✅ shipped (PR #6): Cognito + SigV4 + market-token handshake + ama-* headers + 10 respx-mocked tests.
- **v1.c-2** ✅ shipped (PR #9): `AeroplanProvider(use_browserbase=True)` with auto-mint Cognito IdentityId. Live testing revealed (a) `page.evaluate(fetch)` to `akamai-gw.dbaas.aircanada.com` is blocked by Dynatrace RUM + Kasada + Angular Zone.js before the request leaves the page, and (b) the auto-minted *anonymous* Cognito identity is 403-denied at the market-token resource by AC's IAM policy.

The shipped code stays in the tree as scaffolding for v2.a — the endpoint discovery (`akamai-gw.dbaas.aircanada.com`, `dapidynamicplus`, x-api-key `Z5R8Rm…`, IdentityPoolId `us-east-2:4a7f6b48-…`) is still valid input. What changes is *whose IAM role signs the request*: v2.a's authenticated session uses the logged-in user's role, which (we expect) the IAM policy permits.

See [`docs/STRATEGY.md`](STRATEGY.md) strategic revisions log for the full reasoning.

---

## v2.a — Authenticated-session foundation 🟡 next (design pending)

**Goal:** Build the architecture under design: `SessionManager` + `op` (1Password CLI) wrapper + per-program login adapter pattern + Browserbase login driver + cached `storageState` encrypted via 1Password secure-note. First use case is Aeroplan (the forcing function for the pivot).

**Plan:** TBD — `/ce-brainstorm` first to land requirements; then `/ce-plan`.

**Pre-brainstorm acceptance gates (to be refined in the plan):**
- [ ] `op` CLI is detected at startup; missing-`op` is a clean error with install instructions, not a crash
- [ ] `autopoints login aeroplan` runs the Browserbase-driven login flow, handles TOTP via `op item get aeroplan --otp`, and persists session state encrypted into a 1Password secure note
- [ ] `autopoints search YYZ LHR 2026-10-15 --live-aeroplan` returns ≥1 real `AwardOffer` using the persisted session (no IAM 403, no fetch block)
- [ ] Session expiry (401 from a search) triggers an automatic re-login + single retry; second failure surfaces as a degraded result with `warnings`
- [ ] Per-program `LoginAdapter` interface is documented and one alternative implementation (stub for AA) exists to validate the abstraction shape
- [ ] No regression in chart-floor fallback: if `op` is unavailable or all sessions are stale and re-login fails, search continues with chart-floor data + warnings
- [ ] CI green

---

## v2.b — Live-endpoint canaries ⬜

**Goal:** Nightly synthetic search per live provider; alert on failure. Replaces the previous "quarterly refresh" framing which was the wrong model for the actual failure modes (endpoint rotation, session expiry, anti-bot escalation are unscheduled).

**Acceptance gates:**
- [ ] Cron job runs nightly, fires one canary `SearchRequest` per live-configured provider
- [ ] On canary failure, emit a Discord alert with the provider, error message, and timestamp
- [ ] Canary state (last success per provider) is queryable via `autopoints status`
- [ ] Three consecutive nightly failures auto-disable the provider (sets a `provider_disabled` flag); user re-enables manually after fixing

---

## v2.c — AA direct via authenticated session ⬜

**Goal:** Validate the per-program adapter abstraction by adding AA as the second authenticated-session provider. Cloudflare-vs-PerimeterX classification (previously a load-bearing distinction at v1.5) is less relevant under authenticated sessions — we're inside the auth boundary, not testing it.

**Acceptance gates:**
- [ ] `autopoints login aa` works end-to-end via the same `LoginAdapter` interface v2.a defined
- [ ] `autopoints search DFW LAX 2026-10-15 --live-aa` returns ≥1 real AAdvantage `AwardOffer`
- [ ] Session reuses cleanly across at least 10 searches without re-login
- [ ] CI green

---

## v2.d — BA Avios via authenticated session ⬜

**Goal:** Add BA. The earlier "v1.b — iOS-app mitmproxy capture, 2–4d" plan is replaced by reusing the authenticated-session pattern against ba.com / loyalty.ba.com. `ba_rewards` retained as a spec artifact only.

**Acceptance gates:**
- [ ] `autopoints login ba` handles BA's login (incl. any partial-MFA flow they use)
- [ ] `autopoints search LHR JFK 2026-10-15 --live-ba` returns Avios + taxes matching public ba.com display for a known route
- [ ] CI green

---

## v2.e — Delta via authenticated session + 1Password TOTP ⬜

**Goal:** Un-drop Delta. MFA wall that justified earlier deprioritization is solved by `op item get delta --otp` flowing into the login adapter.

**Acceptance gates:**
- [ ] `autopoints login delta` completes including TOTP from 1Password
- [ ] `autopoints search ATL HND 2026-10-15 --live-delta` returns at least one Delta SkyMiles `AwardOffer`
- [ ] CI green

---

## v2.f — JetBlue via authenticated session ⬜

**Acceptance gates:**
- [ ] `autopoints login jetblue` and `--live-jetblue` work end-to-end for a JFK-LAX search

---

## v2.g — Virgin Atlantic live ⬜

**Goal:** Uncontested, stable login UI. Also the SkyTeam-partner sanity check: assert empirically that VS surfaces useful Delta-metal inventory (the assumption STRATEGY.md previously asserted without evidence).

**Acceptance gates:**
- [ ] `autopoints search JFK LHR 2026-10-15 --live-vs` returns VS Flying Club awards
- [ ] A known Delta-metal partner award shows up in VS results for at least one transcon route — validates the SkyTeam-routes-Delta-value claim

---

## v2.h — MCP server wrapper ⬜

**Goal:** Wrap the existing `--json` CLI surface as FastMCP tools. Absorbs the `~/points-deals` server skeleton; once shipped, retire `points-deals`.

**Acceptance gates:**
- [ ] `autopoints-mcp` binary starts a FastMCP stdio server
- [ ] `claude mcp add autopoints stdio /path/to/autopoints-mcp` registers cleanly with Claude Code
- [ ] Four MCP tools exposed: `search_award`, `compare_routes`, `get_transfer_paths`, `get_balances`
- [ ] All four tools' JSON output matches the CLI `--json` shape
- [ ] `~/points-deals` is archived with a README pointer to autopoints

---

## v2.i — Stale-availability re-verifier ⬜

**Goal:** Before any watchlist alert fires, re-hit the source for that specific (date, cabin, program). If it disappeared, suppress. Closes the pointsyeah complaint about phantom seats.

**Note on sequencing:** earlier drafts of this roadmap sequenced this *after* multiple live providers shipped, but per the 2026-06-08 strategy revision, re-verification ships before watchlists go autonomous to avoid phantom alerts in the interim. The re-verify call is cheap and reuses the same session as the original search.

**Acceptance gates:**
- [ ] Watchlist alerts pass a re-verify call before firing
- [ ] When re-verify returns 0 results, alert is suppressed and the suppression is logged
- [ ] False-positive rate on test fixtures drops below 5%

---

## v3 — Multi-surface polish (when v2 lands)

**Goal:** Make the autonomous-background experience durable. Surface `--arrive-before` / `--live-*` through FastAPI and Discord with the same shape as the CLI/MCP.

**Acceptance:** scoped per-component when planned — major themes are multi-surface parity (FastAPI/Discord/MCP), global Browserbase concurrency cap, credential storage on the Linux NAS target via 1Password Connect server, and one watchlist running autonomously for a week without manual intervention.

---

## How to use this roadmap

1. Each milestone has explicit, demoable acceptance gates. Don't move on until the gates pass.
2. Plans (in `docs/plans/`) hold the per-unit implementation detail. The roadmap holds the *user-facing outcome* gates.
3. Status mark — `✅ done`, `🟡 in progress`, `❌ invalidated`, blank — at the top of each section. Update as you ship.
4. PR descriptions should reference the milestone gate they unblock so the PR check + the milestone gate are clearly tied.
5. If a gate keeps failing for 2+ PR rounds, revisit the milestone scope. A gate that doesn't fail occasionally probably isn't testing the right thing.
6. Invalidated milestones stay in the doc with their reasoning preserved — sequence shifts are easier to evaluate when you can see what was abandoned and why.
