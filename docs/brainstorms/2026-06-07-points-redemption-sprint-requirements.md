# Points Redemption Sprint — Requirements (v0 revised after ce-doc-review)

**Date:** 2026-06-07
**Revised:** 2026-06-07 (after ce-doc-review round 1 surfaced critical schema, environment, and scope gaps)
**Forcing function:** Book LAX → any NYC airport, depart 2026-06-14, arrive < 08:00 ET on 2026-06-15.
**Mode:** Single-day foundational build. Manual fallback path for the Sunday booking decouples scope from deadline.

## Why this was revised

Original requirements committed to ship 4 direct providers + MCP + Discord + NAS deploy + auth scaffold in one calendar day. ce-doc-review surfaced:

- The **arrival-time filter requires a schema migration nobody scoped** — `FlightOffer`, `AwardOffer`, `SearchRequest`, `Watchlist`, and `_signature()` all carry only `depart_date: date` and need time-of-day fields and dedup updates.
- The **Keychain auth scaffold breaks on the Linux NAS Docker target** (no Keychain in Linux containers; `keyring` silently falls back to plaintext).
- The **MCP server has no transport / auth model specified** — `add_watchlist` and `run_watchlists` are write-capable, would drain Browserbase budget if LAN-exposed.
- **AA award pricing is hidden behind login + SMS MFA**; logged-out scrapes return inaccurate data.
- **`BrowserbaseAwardProvider` shared base** designed against 4 unbuilt consumers violates the project's own YAGNI rule.
- The **forcing function is satisfiable in ~15 min by manual search** on aa.com / delta.com / jetblue.com. The original scope used it as rhetorical cover for a strategy bet.

This revision separates **the foundational change that genuinely belongs in the codebase** (cash-provider swap + schema migration + one direct provider as a working example) from **the strategy bet** (4 direct programs + Stagehand for the hard ones), which moves to phase 2 gated on evidence rather than enthusiasm.

## Outcome (v0)

A CLI invocation:

```
autopoints search LAX NYC 2026-06-14 --arrive-before 08:00ET --pax 1 --cabin economy
```

returns a ranked list combining:

- Live cash baseline from Google Flights (via Browserbase) for LAX→{JFK,LGA,EWR} on the chosen date
- Live Alaska Mileage Plan award availability for the same date — partner-friendly, lightest backend, cheapest to ship
- Chart-floor pricing for existing AC / BA / VS providers (unchanged from v0.0)
- Arrival-time filter applied at the orchestrator's post-rank step

The **Sunday booking decision** itself is made by combining v0's output with **manual checks on aa.com / delta.com / jetblue.com** while v0 ships. Direct AA, Delta, JetBlue live providers move to phase 2.

## In Scope (must ship today)

| Area | What lands | Why |
|---|---|---|
| Cash provider | `providers/google_flights.py` via Browserbase + Playwright. Replaces Amadeus (decommissioned 2026-07-17). | Amadeus death is independent of the sprint; this is foundational. |
| Schema migration | Add `departure_time: time \| None`, `arrival_time: time \| None`, `arrival_date: date \| None`, `origin_tz`, `dest_tz` to `FlightOffer` and `AwardOffer`. Add same to `SearchRequest`. Update `_signature()` to include arrival time when present. | The arrival-time filter cannot work without this. |
| CLI filter | `--arrive-before HH:MM<TZ>` on `autopoints search`. Orchestrator applies it as a post-rank filter against `arrival_time` + `arrival_date`. | Forcing function exists at the CLI. FastAPI/MCP/Discord propagation deferred. |
| Watchlist schema | SQLite column add: `arrive_before_local`. Backfill NULL. | If users save the Sunday search as a watchlist, the filter must persist. |
| Direct provider (1) | `providers/alaska.py` — hand-rolled Playwright via Browserbase. Lightest backend, partner sweet spots (Cathay/JAL/Qatar). | Validates the direct-program pattern with one real consumer for the base class extraction in phase 2. |
| Aeroplan | Live provider already opt-in; mark `use_live_aeroplan` flag as deprecated in CLI/API docs. No code change needed. | Hostname is NXDOMAIN; chart-floor is current state. |
| Strategy update | `docs/STRATEGY.md` revised: direct-program coverage is **on the roadmap**, with v0 shipping Alaska; AA/Delta gated on a 30-min Stagehand probe (deferred to phase 2). | Aligns strategy with actual evidence rather than enthusiasm. |
| Sunday booking | Manual: I check aa.com / delta.com / jetblue.com directly while v0 ships. v0 covers Google Flights cash + Alaska award. | Decouples deadline pressure from sprint scope. |

## Phase 2 (post-6/14, gated on evidence)

| Area | Why deferred | Gate |
|---|---|---|
| FastMCP server | Not on critical path for Sunday booking. Transport/auth model unresolved. | Decide transport (stdio vs HTTP+token) before scoping |
| Discord slash-command for `--arrive-before` | Watchlist runner needs arrive_before plumbing first | After v0 lands |
| JetBlue direct provider | Easy backend; not on critical path | After Alaska validates pattern |
| AA + Delta direct providers (Stagehand) | Untested vs PerimeterX/Akamai; logged-out data quality unknown; AA MFA flow unscoped | **30-min Stagehand probe must succeed** + AA login flow scoped |
| `BrowserbaseAwardProvider` base class | Premature abstraction across unbuilt consumers | Extract after 2-3 direct providers ship with known shared surface |
| Keychain auth helper | Conflicts with Linux Docker NAS target; no current consumer beyond Browserbase API key (which goes in `.env`) | When the first credential-bearing scraper ships (live balance fetch) |
| Bilt transfer ratios | Verify against actual booking candidates first | When user identifies a real Bilt-routed redemption |
| NAS re-deploy | Already deployed; not blocking Sunday booking | Bundle with phase 2 deploys |
| BA Avios iOS API port (`timrogers/ba_rewards`) | Highest-leverage per STRATEGY.md; not displaced — just sequenced after v0 schema migration | Open to schedule immediately after v0 |
| Stale-availability re-verifier | Strategic differentiator per STRATEGY.md; scales with provider count | Schedule before adding 2+ more live providers |
| Live balance auto-fetch from logged-in sessions | Triggers a different legal posture (CFAA-relevant; authenticated automated access) | Explicit legal-posture decision first |

## Strategy delta (revised)

Update `docs/STRATEGY.md` to:

1. **Direct-program coverage is on the roadmap** for the 4 user-held programs (Alaska, AA, Delta, JetBlue), shipped incrementally with Alaska in v0.
2. **Stagehand-driven scraping for AA/Delta is a candidate**, not the default. A 30-min probe against PerimeterX (AA) and Akamai (Delta) gates whether it earns "default" status.
3. **Hand-rolled Playwright remains default** for light backends (Alaska, JetBlue).
4. **United stays out** (no direct membership).
5. **The "What we'll never do" rule about paid integrations is amended**: Browserbase is an accepted dependency; an explicit revert path is documented (revert AA/Delta to "skip" if Browserbase becomes unavailable or expensive).
6. **BA Avios iOS API port remains the highest-leverage partner-side move** and is scheduled immediately after v0.

## Open Questions (carried forward to phase 2 scoping)

These are the doc-review findings the v0 cut defers rather than resolves. Each must be answered before the corresponding scope item can move from phase 2 to in-scope:

- **Linux credential storage strategy.** When live balance fetch lands, what stores per-program passwords in the NAS Docker container? Options: Docker secrets, mounted file, env vars per program, separate vault container.
- **MCP transport model.** stdio-only (local-process) vs HTTP+bearer-token. Affects who can call `add_watchlist` / `run_watchlists`.
- **AA logged-in scraping + MFA bridge.** aa.com hides saver pricing behind login; new-device login requires SMS MFA. Build an SMS bridge? Pin a device session? Or accept logged-out's lower data quality?
- **Stagehand reliability against PerimeterX + Akamai.** 30-min probe required. Outcome shapes whether AA/Delta direct ships at all in v1.
- **Stagehand prompt-side credential exposure.** If Stagehand drives the login form via prompts containing credentials, those strings transit Anthropic/OpenAI logs. Resolve by injecting pre-authenticated cookies instead.
- **Browserbase parallel-session ceiling at runtime.** Orchestrator's `asyncio.gather` fans out N providers × M days. Needs a global semaphore or per-provider rate limit when total Browserbase providers exceed 1.
- **Per-day Browserbase cost cap** for the watchlist runner. Hard cap or budget alert before unleashing the runner on the new providers.
- **Watchlist `_signature()` evolution.** Once arrival-time persists, dedup must include time to avoid collapsing two different redeyes to one signature.
- **Legal posture amendment.** AA-specific litigation history + Browserbase as third-party log custodian = different posture than the seats.aero/AC frame. Document the new boundary before AA direct ships.
- **Browserbase revert path.** If Browserbase becomes unavailable, does AA/Delta direct revert to "skip" or migrate to a different stealth-browser vendor?

## Risks (v0)

| Risk | Mitigation |
|---|---|
| Google Flights deploys a CAPTCHA against Browserbase stealth | Browserbase auto-solves; if persistent, fall back to a cached "estimate" mode for the demo with explicit `confidence: low` |
| Alaska's award-search backend has changed since last public RE | Day-1 hands-on inspection in browser before writing the scraper |
| Schema migration breaks existing tests (62 currently pass) | Migration adds optional fields only; existing tests pass unchanged. New tests cover time-bearing paths. |
| Watchlist column migration | Single `ALTER TABLE watchlists ADD COLUMN arrive_before_local TEXT NULL` — safe; existing watchlists keep working |
| v0 ships but Sunday flight booking decision needs more programs | Mitigated by parallel manual checks on aa.com / delta.com / jetblue.com — the booking is decoupled from v0 |

## Dependencies / Assumptions

- User has an active Browserbase API key (env var `BROWSERBASE_API_KEY`, not Keychain).
- Google Flights does not deploy a CAPTCHA against Browserbase stealth + residential proxies for the LAX-NYC query.
- Alaska's award-search endpoint is reachable and returns parseable JSON (or rendered HTML we can scrape).
- Existing autopoints provider ABC, `Orchestrator`, `Watchlist`, `WatchlistRunner` work as the 62-pass test suite documents.

## Handoff

Next step: `/ce:plan` against this **revised** v0 requirements doc to produce concrete file-level execution plan. Then `/ce:work` executes sequentially in the main worktree — no parallel sub-agents needed for v0's smaller scope.

Manual track in parallel (does not block v0): I check aa.com / delta.com / jetblue.com for the Sunday LAX-NYC redeye options arriving < 08:00 ET on 6/15.

## Round 1 ce-doc-review findings — disposition

| # | Finding | Disposition |
|---|---|---|
| F1 (feasibility, 100) | Schema lacks time fields | **In scope (schema migration row)** |
| F2 (feasibility, 75) | Browserbase cost via watchlist runner | **Phase 2 — per-day cap before runner re-enabled** |
| F3 (feasibility, 75) | Orchestrator concurrency vs Browserbase ceiling | **Phase 2 — when 2nd Browserbase provider ships** |
| F4 (feasibility, 50) | Aeroplan flag wording | **In scope (deprecation note row)** |
| F5 (feasibility, 100) | Keychain incompatible with Linux | **Phase 2 — auth scaffold deferred until live balance fetch** |
| F6 (feasibility, 75) | `_signature()` doesn't carry time | **In scope (schema migration row)** |
| F7 (feasibility, 75) | Stagehand-as-default before probe | **Resolved by Strategy delta point 2** |
| F8 (feasibility, 100) | `mcp/` directory doesn't exist | **Phase 2 — MCP deferred** |
| F9 (feasibility, 75) | Watchlist persists no arrive-before | **In scope (watchlist schema row)** |
| P1 (product, 75) | Premise reversal addresses only anti-bot, not noisy CPP | **Resolved by sequencing AA/Delta behind a probe** |
| P2 (product, 75) | BA iOS API displaced | **Resolved — BA iOS scheduled immediately after v0** |
| P3 (product, 75) | Forcing function disproportionate to scope | **Resolved by manual Sunday booking + v0 cut** |
| P4 (product, 75) | Maintenance compounding unexamined | **Open Question — maintenance budget needed before phase 2 commitments** |
| P5 (product, 75) | Auth + Bilt are speculative | **Resolved — both deferred to phase 2** |
| S1 (security, 100) | Linux Docker credential storage | **Open Question** |
| S2 (security, 100) | MCP transport / auth model | **Open Question** |
| S3 (security, 75) | Stagehand prompt credential exposure | **Open Question** |
| S4 (security, 75) | Browserbase session isolation | **In scope — fresh session per provider invocation** |
| S5 (security, 75) | Onboarding wizard plaintext over HTTP | **Phase 2 — pre-existing; not new attack surface this sprint** |
| S6 (security, 50) | ToS / CFAA exposure | **Open Question — legal posture amendment** |
| SG1 (scope, 75) | MCP not on critical path | **Resolved — phase 2** |
| SG2 (scope, 75) | Shared base premature | **Resolved — phase 2** |
| SG3 (scope, 75) | PR-gating overhead | **Resolved — sequential build, no sub-agents in v0** |
| SG4 (scope, 75) | NAS re-deploy + Discord smoke off critical path | **Resolved — phase 2** |
| SG5 (scope, 75) | Filter propagation across 4 surfaces | **Resolved — CLI + orchestrator only in v0** |
| SG6 (scope, 50) | Auth scaffold speculative | **Resolved — phase 2** |
| SG7 (scope, 50) | BA iOS port skip order | **Resolved — scheduled immediately after v0** |
| A1 (adversarial, 75) | Stagehand vs PerimeterX folk wisdom | **Resolved — gated on probe** |
| A2 (adversarial, 75) | Day-1 abstraction across 4 unbuilt providers | **Resolved — base class deferred** |
| A3 (adversarial, 75) | Legal posture delta | **Open Question** |
| A4 (adversarial, 75) | Auth scaffold w/o consumer | **Resolved — phase 2** |
| A5 (adversarial, 75) | 3 unstated assumptions collapse day-1 | **Resolved by v0 cut** |
| A6 (adversarial, 75) | Strategy load-bearing on paid 3rd party | **Resolved by Strategy delta point 5** |
| A7 (adversarial, 75) | Stagehand failure mode binary | **Open Question — `confidence` field for Stagehand results** |
| A8 (adversarial, 75) | No mention of MFA / login walls | **Open Question — AA logged-in flow scoped before AA provider** |
| A9 (adversarial, 50) | Phantom availability scales with providers | **Phase 2 — re-verifier before adding 2+ live providers** |
