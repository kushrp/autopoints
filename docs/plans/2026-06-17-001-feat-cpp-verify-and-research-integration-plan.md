---
title: "feat: Verify keyless CPP path + integrate research + author v2.a plan"
type: feat
status: active
created: 2026-06-17
origin: docs/brainstorms/2026-06-08-v2a-authenticated-sessions-requirements.md
---

# feat: Verify keyless CPP path, integrate research data, author v2.a token-refresh plan

**Target repo:** autopoints (kushrp/autopoints). Branch: `feat/v2a-plan-and-cpp-integration`. Never commit main.

## Summary

Three bounded deliverables in one PR. First, prove the existing keyless path (Google
Flights cash + chart-floor award) runs end to end and prints ranked cents-per-point,
with a deterministic `--demo` regression test as the gate. Second, fold this session's
verified June-2026 research into the static data files without schema changes. Third,
author the v2.a authenticated-session token-refresh plan as its own `docs/plans/` doc,
sourced from the existing brainstorm.

The point of deliverable 1 is to confirm a real CPP value is reachable today with zero
keys and zero manual intervention; authenticated live providers are future work, fully
specified by deliverable 3.

---

## Problem Frame

autopoints already has the pieces for a keyless CPP read: `GoogleFlightsProvider` (cash
via `fli`), `StaticChartProvider` (chart-floor award for AC/BA/VS), and the CPP engine in
`autopoints/pricing/cpp.py`. What is missing is (a) a verified, regression-guarded
demonstration that a search prints ranked CPP without credentials, (b) current valuation
and transfer-bonus data, and (c) an execute-ready plan for the authenticated-session
sourcing that the STRATEGY.md build order calls v2.a.

A reality check while reading the code reshaped deliverable 2. The CPP engine
(`build_redemption`) only treats `UR`, `MR`, and `DIRECT` as transfer currencies, and it
values **award programs**, not currencies. So the originally-scoped Citi (TYP) -> Qatar
Avios and Citi -> Accor bonuses would be inert: `TYP` is not a modelled transfer
currency, `QR`/`Accor` are not in `transfer_ratios.json`, and Accor is a hotel program
outside this flights tool. The fix is to load the engine-compatible bonuses this
session's research also surfaced and which the ratio table already supports: MR ->
Flying Blue (`AF`) and UR -> Virgin Atlantic (`VS`). Both pairs exist in
`transfer_ratios.json`, so `active_bonus()` will actually apply them.

---

## Requirements

- R1: `autopoints search <O> <D> <date>` produces ranked CPP rows using Google Flights
  cash + chart-floor award, no credentials, no manual steps. The `--demo` path is the
  deterministic test surface when the live `fli` call flakes.
- R2: `valuations.json` gains Capital One, Citi ThankYou, and Bilt reference values and a
  refreshed `_meta`, keeping the flat `{program: cpp}` shape.
- R3: `transfer_bonuses.json` gains engine-compatible, schema-correct active bonuses that
  `active_bonus()` reads and `build_redemption()` applies, proven by a test.
- R4: A v2.a authenticated-session token-refresh plan exists in `docs/plans/`, covering
  the three refresh mechanisms as one coherent design, with the gating manual probe,
  SessionManager + LoginAdapter design, 1Password session storage, and R7 anti-ban
  guardrails, sequenced per STRATEGY.md (Aeroplan first).

---

## Key Technical Decisions

- **Demo path is the regression gate, not the live call.** `fli` flakes ~20% per its own
  provider docstring, so a CI assertion on a live Google Flights call would be flaky.
  The deterministic gate runs `--demo`; a separate, non-CI smoke step exercises the live
  path. (see origin repo `autopoints/providers/google_flights.py` docstring)
- **Bonus entries use the engine's real key shape.** `active_bonus()` reads `from`, `to`,
  `start`, `end`, `multiplier`. Entries must use those keys, with `from` in {UR, MR} and
  `to` a program present in `transfer_ratios.json`.
- **Substitute engine-compatible bonuses for the inert ones.** MR->AF 25% (1.25) and
  UR->VS 30% (1.3) replace the inert TYP->QR / ->Accor entries. Both verified June 2026.
- **Currency valuations are reference data.** `valuations.get(award.provider)` looks up
  award programs, not currencies, so C1/TYP/BILT are informational, consistent with the
  existing UR/MR reference entries. No engine change.
- **v2.a is a plan doc only here.** No authenticated-session code lands in this PR; the
  doc is the deliverable. The gating aircanada.com probe stays a documented human step.

---

## Implementation Units

### U1. Verify keyless CPP path and add a demo regression test

**Goal:** Prove a search prints ranked CPP with no keys, and guard it.

**Requirements:** R1

**Dependencies:** none

**Files:**
- `tests/test_cpp_demo_smoke.py` (new)
- `autopoints/cli/main.py` (read-only unless the run surfaces a defect)
- `autopoints/search/orchestrator.py` (read-only unless a defect surfaces)

**Approach:** Run `uv run autopoints search JFK PHX 2026-06-15 --demo` and confirm it
prints CPP rows sorted by value with verdict labels. Then run a live (non-demo) search
once to confirm the Google Flights + chart-floor wiring returns a real CPP, tolerating
`fli` flakiness (retry once; if still down, record that the live path is environment
-dependent and the demo path is the gate). Add a test that drives the orchestrator in
demo mode and asserts non-empty, value-sorted `RedemptionResult`s with finite CPP.

**Patterns to follow:** existing tests under `tests/`, the demo provider in
`autopoints/providers/demo.py`, the orchestrator fan-out in
`autopoints/search/orchestrator.py`.

**Test scenarios:**
- Happy path: demo search for a domestic route returns >=1 `RedemptionResult`, CPP
  strictly descending (or non-increasing) across rows.
- Edge: a route with no chart region match returns cash-only / empty award rows without
  raising.
- Integration: orchestrator fan-out over (cash provider, award provider) yields at least
  one paired redemption with a populated `verdict`.

**Verification:** `autopoints search JFK PHX 2026-06-15 --demo` prints ranked CPP rows;
the new test passes under `uv run pytest`.

### U2. Refresh valuations.json with June-2026 reference values

**Goal:** Add Capital One, Citi ThankYou, Bilt; refresh `_meta`.

**Requirements:** R2

**Dependencies:** none

**Files:** `autopoints/programs/valuations.json`

**Approach:** Add `C1: 1.85`, `TYP: 1.9`, `BILT: 2.2`. Update `_meta.source` to a
June-2026 TPG/Frequent Miler reference and `_meta.last_reviewed` to `2026-06-17`. Keep
the flat shape and existing entries untouched.

**Test scenarios:** Test expectation: none -- static reference data; `loader.valuations()`
already filters `_` keys and is covered. Optionally assert the JSON parses and the three
keys are present in an existing data-integrity test if one exists.

**Verification:** `python -c "import json,pathlib; json.loads(pathlib.Path('autopoints/programs/valuations.json').read_text())"` succeeds and the three keys exist.

### U3. Refresh transfer_bonuses.json with engine-compatible bonuses + uplift test

**Goal:** Add live bonuses the engine actually applies, and prove the uplift.

**Requirements:** R3

**Dependencies:** none

**Files:**
- `autopoints/programs/transfer_bonuses.json`
- `tests/test_transfer_bonus_uplift.py` (new)

**Approach:** Append to `active` two entries in the engine's key shape:
`{from: "MR", to: "AF", multiplier: 1.25, start: "2026-06-01", end: "2026-06-30"}` and
`{from: "UR", to: "VS", multiplier: 1.30, start: "2026-06-01", end: "2026-07-14"}`. Do
**not** add TYP->QR or ->Accor (inert: TYP is not a modelled currency, neither program is
in `transfer_ratios.json`, Accor is a hotel). Update `_meta.last_reviewed`. Add a test
that builds a redemption for MR->AF on a date inside the window and asserts
`effective_points_required < points_required` and the "includes 25% transfer bonus" note.

**Patterns to follow:** `active_bonus()` and `build_redemption()` in
`autopoints/pricing/cpp.py`; existing pricing tests.

**Test scenarios:**
- Happy path: MR->AF redemption with `depart_date` in window applies 1.25 -> effective
  points = round(points / 1.25); note present.
- Edge: same pair with `depart_date` after `end` applies no bonus (multiplier 1.0).
- Edge: a `from`/`to` pair with no bonus entry returns multiplier 1.0 unchanged.

**Verification:** new test passes; `active_bonus("MR","AF",<in-window date>)` returns 1.25.

### U4. Author the v2.a authenticated-session token-refresh plan

**Goal:** Produce the execute-ready v2.a plan doc.

**Requirements:** R4

**Dependencies:** none

**Files:** `docs/plans/2026-06-17-002-feat-v2a-authenticated-sessions-plan.md` (new)

**Approach:** Translate the brainstorm
(`docs/brainstorms/2026-06-08-v2a-authenticated-sessions-requirements.md`) into a plan
with implementation units. Frame the user's three refresh mechanisms as one coherent
design, not alternatives: (a) one Browserbase-driven login captures the Playwright
`storageState` session envelope; (b) 1Password CLI/Connect supplies credentials + TOTP so
re-login is automated; (c) a 401/403 -> invalidate -> refresh-once -> retry loop plus
chart-floor fallback keeps the user out of the loop, with the Discord slash command as the
only manual re-login surface. Include: step-0 gating manual probe (~1hr aircanada.com
login + DevTools header capture, explicitly a HUMAN step, not agent-executed);
`SessionManager` (get/invalidate/refresh) + per-program `LoginAdapter` design (Aeroplan
concrete first, abstraction extracted at v2.c/AA); R3 1Password secure-note session
storage; R7 anti-ban guardrails (60s + jitter rate limit, daily cap, single concurrency,
URL allowlist, read-only method gating, auto-freeze on 429/challenge). Carry the
$0/mo-recurring and read-only-never-book constraints. Sequence per the STRATEGY.md build
order.

**Test scenarios:** Test expectation: none -- planning document, no executable behavior.

**Verification:** the doc exists, follows the plans naming/format convention, and covers
all four required content blocks (3 mechanisms, step-0 probe, SessionManager/LoginAdapter,
R3 storage, R7 guardrails).

---

## Scope Boundaries

In scope: the keyless CPP verification + regression test, the two static data refreshes,
and authoring the v2.a plan doc.

### Deferred to Follow-Up Work
- Implementing v2.a authenticated sessions (the doc this PR authors is the spec).
- Live transfer-bonus scraping (doctorofcredit / Frequent Miler) to replace manual JSON.
- A Browserbase + Playwright cash fallback for when `fli` breaks.

### Out of scope (per STRATEGY.md)
- seats.aero or any commercial-aggregator dependency.
- Booking automation. Read-only always.
- Hotel redemptions.
