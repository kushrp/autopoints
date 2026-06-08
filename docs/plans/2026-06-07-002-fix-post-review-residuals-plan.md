---
title: "fix: address 5 deferred ce-code-review residuals from PR #3"
date: 2026-06-07
type: fix
status: active
origin: https://github.com/kushrp/autopoints/pull/3
---

# fix: post-review residuals

**Target repo:** autopoints (this repo)
**Origin:** PR #3 (merged at commit 9db8437); ce-code-review run at `/tmp/compound-engineering/ce-code-review/20260607-200000-v0review/review.json`

---

## Summary

PR #3 shipped the v0 points-redemption sprint and applied 7 mechanical fixes during code review. The merged PR's "Residual Review Findings" section enumerated 5 items deferred from that auto-apply: one cross-TZ correctness bug, one missing `return_exceptions=True`, one silent-fallback warning, one missing logging call, and one design call where the new `--arrive-before` filter never actually fires against v0 providers. Each is a small, focused change with concrete test scenarios.

## Problem Frame

The v0 forcing function (LAX → NYC redeye arriving < 08:00 ET) is answered by Google Flights cash data via `fli`, which populates departure/arrival times. The `--arrive-before` filter introduced in v0/U3 inspects `award_offer.arrival_time` only — every chart-floor award provider returns no times so the filter passes everything, and the Alaska skeleton always raises. End result: the filter UI promises filtering it never delivers for the forcing function. Independently, the orchestrator's cross-TZ math is wrong, the watchlist runner cancels siblings on any one failure, the parse-error path returns unfiltered results without telling the user, and the cash provider's broad catch logs nothing. All five were flagged by ce-code-review with cross-persona agreement on the high-severity items.

## Requirements

Each item below traces to a specific finding in PR #3's body and the ce-code-review JSON artifact:

- **R1** — Cross-TZ filter math: `_filter_arrive_before` correctly handles offers whose `dest_tz` differs from the filter TZ (e.g., LAX→NRT filtered with `08:00ET` should drop / keep based on the offer's actual landing time in the offer's tz).
- **R2** — Filter applies to cash arrival times too: an offer with `cash_offer.arrival_time` populated but `award_offer.arrival_time = None` is subject to the filter against the cash side. Both-None still passes (chart-floor compatibility).
- **R3** — `run_all` no longer cancels siblings: a failure in one watchlist's `build_orchestrator` or `run_one` produces a degraded `WatchlistRunResult` (empty hits, warnings carry the exception text), and other watchlists continue.
- **R4** — Parse-error warning carries actionable context: a malformed `arrive_before_local` arriving at the orchestrator surfaces a warning prefixed with `arrive-before filter disabled, returning unfiltered results:` so the user knows their filter didn't take effect.
- **R5** — `GoogleFlightsProvider.search` logs via `logger.exception` before wrapping into `ProviderError`, so persistent fli failures surface beyond a single one-line `outcome.warnings` entry.

Existing 87 tests must continue to pass. New test scenarios per unit.

## Key Technical Decisions

- **TZ math anchors on `offer.dest_tz`, falls back to filter tz.** The fix in U1 stops conflating "the day of arrival" (which is a property of the offer in its own tz) with "the filter's clock face." A redeye landing 06:00 JST on the day after departure in the filter's eyes should be `arr_dt = datetime.combine(offer.arrival_date, offer.arrival_time, tzinfo=offer.dest_tz or filter_tz)`. The cutoff is `datetime.combine(arr_dt.astimezone(filter_tz).date(), filter_wall, tzinfo=filter_tz)`. Both sides are then comparable in absolute time. Chart-floor offers (no tz info) keep falling back to filter tz, preserving back-compat.

- **Filter check pattern: `min(award_arr, cash_arr)` when both present, else whichever is present.** Per the origin LFG prompt option (b), U5 widens the filter to inspect both `award_offer.arrival_time` and `cash_offer.arrival_time`. When both are populated, use the earlier arrival (safer for the user — a cash flight that arrives later than the award is still bookable on award). When only one side is populated, use that. When neither is populated, pass through (chart-floor compatibility unchanged).

- **`run_all` mirrors `orchestrator.run`'s pattern.** Use `asyncio.gather(*tasks, return_exceptions=True)` and post-process the result list: if an entry `isinstance(BaseException)`, build a degraded `WatchlistRunResult(watchlist=wl, hits=[], warnings=[str(exc)])`. The watchlist identity is preserved by tracking `(wl, awaitable)` pairs through the gather.

- **`google_flights.py` adds module-level `logger = logging.getLogger(__name__)`.** Project convention is no logging module (warnings flow as data), but ce-code-review's reliability reviewer flagged the BLE001 catch-all as making persistent failures invisible. Adding one `logger.exception` call inside the catch is the minimal change that satisfies the finding without changing the outcome contract — the `outcome.warnings` channel remains the user-facing surface.

## Implementation Units

### U1. Cross-TZ correctness in `_filter_arrive_before`

**Goal:** Fix the timezone math so `_filter_arrive_before` correctly compares offers whose `dest_tz` differs from the filter's TZ. Add a cross-TZ test fixture that would have caught the existing same-tz oversight.

**Requirements:** R1

**Dependencies:** none (foundational for U5)

**Files:**
- `autopoints/search/orchestrator.py` (modify) — `_filter_arrive_before`
- `tests/test_orchestrator.py` (modify) — extend filter test suite

**Approach:**
1. Replace the existing `cutoff_dt = datetime.combine(offer.arrival_date, wall, tzinfo=tz)` line. The bug is that `offer.arrival_date` is in `dest_tz` but `tz` is the filter's TZ — combining them produces a nonsense moment.
2. New math: build `arr_dt` exactly as today (`datetime.combine(arrival_date, arrival_time, tzinfo=offer_tz)`). Then derive the cutoff *in absolute time* by anchoring to the same calendar day the offer arrives in the filter's TZ. Pseudo-code:
   ```
   arr_dt = datetime.combine(arrival_date, arrival_time, tzinfo=offer_tz)
   filter_day = arr_dt.astimezone(filter_tz).date()
   cutoff_dt = datetime.combine(filter_day, filter_wall, tzinfo=filter_tz)
   keep = arr_dt < cutoff_dt
   ```
3. Same-tz behavior is preserved — when `offer_tz == filter_tz`, `filter_day == arrival_date` and the comparison reduces to the existing case.
4. Chart-floor offers (no `arrival_time` / `arrival_date`) keep passing per existing behavior.

**Patterns to follow:**
- The existing `parse_arrive_before(spec) -> (time, ZoneInfo)` helper stays unchanged — only the filter body changes.
- Continue using `zoneinfo.ZoneInfo` per the project's stdlib-only TZ convention.

**Test scenarios:**
- **Cross-TZ, drops late:** LAX → NRT offer, `arrival_time=08:30`, `arrival_date=2026-10-16`, `dest_tz="Asia/Tokyo"`. Filter `08:00ET` should drop (08:30 JST = 19:30 ET 2026-10-15, still after 08:00 ET on the filter day).
- **Cross-TZ, keeps early:** LAX → NRT offer, `arrival_time=06:00`, `arrival_date=2026-10-16`, `dest_tz="Asia/Tokyo"`. Filter `08:00ET` should keep (06:00 JST = 17:00 ET 2026-10-15; the relevant filter day is 2026-10-15 and 17:00 ET is after 08:00 ET, so this should *drop* — verify the math chooses the correct anchor).
  - This scenario is the one most likely to surface an off-by-one-day. Implementer must pin the expected behavior in the test, with rationale comments explaining which date the cutoff anchors on.
- **Same-tz regression:** Existing `test_arrive_before_drops_late_arrivals` and `test_arrive_before_keeps_early_arrivals` must continue to pass unchanged.
- **Chart-floor still passes:** Existing `test_arrive_before_keeps_chart_floor_results_without_times` must continue to pass.
- **No `dest_tz` on offer:** When `dest_tz=None` the filter falls back to the filter's TZ for both anchors — comparison is well-defined and same as same-tz case.

**Verification:** `pytest tests/test_orchestrator.py -q` passes 6+ scenarios. `pytest -q` passes the full suite (87 baseline + new).

---

### U2. `run_all` uses `return_exceptions=True`

**Goal:** A failure in one watchlist's run does not cancel sibling runs. The failing watchlist surfaces as a degraded result with warnings; others continue normally.

**Requirements:** R3

**Dependencies:** none

**Files:**
- `autopoints/watchlist_runner.py` (modify) — `run_all`
- `tests/test_watchlists.py` (modify) — add degraded-result test

**Approach:**
1. Wrap each `run_one` in a coroutine factory so the watchlist identity is preserved alongside the awaitable.
2. Call `asyncio.gather(*tasks, return_exceptions=True)`.
3. Walk the result list. For each entry: if it's a `BaseException`, construct a degraded `WatchlistRunResult(watchlist=wl, hits=[], warnings=[f"watchlist run failed: {exc!r}"])`. Otherwise use the `WatchlistRunResult` directly.
4. Return the assembled list — order preserved per gather contract.

**Patterns to follow:**
- Mirror `autopoints/search/orchestrator.py:Orchestrator.run`'s `asyncio.gather(*cash_tasks, return_exceptions=True)` then `if isinstance(r, Exception)` pattern.
- Use `f"watchlist run failed: {exc!r}"` (or the `exc.__class__.__name__: {exc}` shape used elsewhere) for the warning text — implementer picks the wording.

**Test scenarios:**
- **Two watchlists, one raises:** Stub `run_one` to raise `RuntimeError("boom")` for the first wl and succeed for the second. `run_all` returns 2 `WatchlistRunResult` entries; first has `hits == []` and warnings include the error text; second is normal.
- **Single watchlist that raises:** Returns a single degraded result, not an empty list.
- **All watchlists succeed:** Existing happy-path test continues to pass.
- **Empty store:** `run_all` returns `[]` when `store.list()` is empty (existing behavior).

**Verification:** `pytest tests/test_watchlists.py -q` passes. Full suite passes.

---

### U3. `ArriveBeforeParseError` warning carries actionable prefix

**Goal:** When the orchestrator catches a parse error from a malformed `arrive_before_local`, the warning sent to `outcome.warnings` clearly states that the filter was disabled and results are unfiltered.

**Requirements:** R4

**Dependencies:** U1 lands first (touches same function body) but doesn't strictly require it; this can land in either order. Plan order keeps U1 first so a single contiguous orchestrator diff lands.

**Files:**
- `autopoints/search/orchestrator.py` (modify) — orchestrator `run`'s filter call site
- `tests/test_orchestrator.py` (modify) — update existing `test_arrive_before_unparseable_spec_warns_instead_of_failing`

**Approach:**
1. In the `try / except ArriveBeforeParseError` block around the `_filter_arrive_before` call, change the appended warning text from `outcome.warnings.append(str(e))` to `outcome.warnings.append(f"arrive-before filter disabled, returning unfiltered results: {e}")`.
2. The exception object's `str(e)` already includes the offending spec and a hint — the prefix just makes the consequence explicit.

**Test scenarios:**
- **Bad spec via orchestrator-level path:** Update existing `test_arrive_before_unparseable_spec_warns_instead_of_failing` — assert `"arrive-before filter disabled" in w` for the warning. The redemptions list still returns unfiltered.
- **Good spec produces no warning:** Existing test confirming clean filter runs continues to pass.

**Verification:** Targeted test passes. Full suite passes.

---

### U4. `GoogleFlightsProvider` logs via `logger.exception`

**Goal:** A persistent fli failure produces a log line at WARNING/ERROR level before being wrapped into `ProviderError`, so the operator running the watchlist runner sees a clear log entry rather than a single one-line `outcome.warnings`.

**Requirements:** R5

**Dependencies:** none

**Files:**
- `autopoints/providers/google_flights.py` (modify) — add module logger, call `logger.exception` inside the broad catch
- `tests/test_google_flights.py` (modify) — assert log emission in the existing wrap-error test

**Approach:**
1. Add module-level `logger = logging.getLogger(__name__)` near the top (after the `from __future__` imports).
2. Inside `except Exception as e:` in `GoogleFlightsProvider.search`, before the `raise ProviderError(...) from e`, call `logger.exception("fli search failed for %s -> %s on %s", origin, destination, depart_date.isoformat())`.
3. Preserve the existing `except ProviderError: raise` short-circuit so we don't double-log when the inner code already raised our typed error (it would still hit the broad `except Exception` otherwise).

**Patterns to follow:**
- No other autopoints provider uses logging today. Per ce-code-review reliability finding's rationale, this is the place to introduce it — it does not change the user-facing contract (warnings still flow via `outcome.warnings`), it just adds operator-facing observability.
- Use `%s` style format strings (the `logging` convention) so the message is built lazily.

**Test scenarios:**
- **Log emission on wrap:** Use pytest's `caplog` fixture; assert that triggering the `except Exception` path emits at least one log record at `logging.ERROR` (via `logger.exception`) with the route info embedded.
- **Existing `test_upstream_exception_wraps_to_provider_error` still passes** — adding logging is additive.
- **No log on `ProviderError` pass-through:** Update `test_provider_error_passes_through` to assert `caplog.records` for the `google_flights` logger remains empty.

**Verification:** Targeted tests pass. Full suite passes. Manual: `python -c "import logging; logging.basicConfig(level=logging.ERROR); import asyncio; from autopoints.providers.google_flights import GoogleFlightsProvider; asyncio.run(GoogleFlightsProvider().search('XXX', 'JFK', __import__('datetime').date(2026,6,14), __import__('autopoints.search.models', fromlist=['Cabin']).Cabin.economy))"` shows the error log (unknown airport triggers `ProviderError`, which the existing short-circuit re-raises — the broad catch isn't hit; use a different sad path or directly invoke a mocked failure to manually verify).

---

### U5. Filter also inspects `cash_offer.arrival_time`

**Goal:** Per the origin LFG prompt's option (b), broaden the filter to drop redemptions whose cash arrival is at or after the cutoff, even when the award side has no time fields (chart-floor case). This makes the v0 `--arrive-before` filter actually fire for the LAX→NYC forcing function, which is answered by cash data via fli.

**Requirements:** R2

**Dependencies:** U1 (uses the redesigned cutoff math)

**Files:**
- `autopoints/search/orchestrator.py` (modify) — `_filter_arrive_before`
- `tests/test_orchestrator.py` (modify) — add scenarios where cash side carries time fields and award side does not

**Approach:**
1. In `_filter_arrive_before`, build candidate `arr_dt` from both `r.award_offer` and `r.cash_offer` using the same tz logic as U1.
2. Decision matrix:
   - If neither side has `arrival_time` + `arrival_date`: pass through (chart-floor compatibility).
   - If only one side has them: use that side's `arr_dt`.
   - If both sides have them: use `min(award_arr_dt, cash_arr_dt)` — safer for the user, since a cash flight arriving later than the award doesn't necessarily disqualify the award redemption from the filter.
3. Compare against the U1-redesigned cutoff in the filter TZ. Drop if `arr_dt >= cutoff_dt`.

**Patterns to follow:**
- Same TZ-resolution helper used in U1. If U1 extracted a `_offer_arrival_dt(offer, filter_tz) -> datetime | None` helper, reuse it for both sides here.

**Test scenarios:**
- **Cash-only times, drops late:** redemption with `award_offer.arrival_time=None` but `cash_offer.arrival_time=09:30`, `cash_offer.arrival_date=2026-06-15`, `cash_offer.dest_tz="America/New_York"`. Filter `08:00ET` drops.
- **Cash-only times, keeps early:** same as above but `cash_offer.arrival_time=07:13`. Filter `08:00ET` keeps.
- **Both sides populated, award later than cash:** award arrives 09:30, cash arrives 07:13 — uses min (07:13) and keeps under `08:00ET`. Documents the "safer for user" intent.
- **Neither side has times (chart-floor + cash-no-time):** passes (existing chart-floor test extended).
- **Forcing-function scenario:** LAX→JFK redemption where `cash_offer.arrival_time=05:25`, `cash_offer.arrival_date=2026-06-15`, `cash_offer.dest_tz="America/New_York"`. Filter `08:00ET` keeps; same redemption with cash arrival `09:30` is dropped. This locks in the v0 forcing-function answer.

**Verification:** Targeted tests pass. Full suite passes. Manual: build a quick orchestrator wrapper with `--arrive-before 08:00ET` against demo data and confirm chart-floor results no longer pass through unchanged when cash side carries times — should reduce row count vs. unfiltered.

---

## Open Questions

None blocking. Implementer-time judgment calls (which are explicit in U1 and U4 above):

- The exact wording of warning text (`f"arrive-before filter disabled, returning unfiltered results: {e}"`) is the planner's suggestion; close synonyms are fine if implementation reveals a better fit.
- Whether to extract a shared `_offer_arrival_dt(offer, filter_tz) -> datetime | None` helper or inline the math in U1 and U5 is the implementer's call based on what reads cleanest.

## Risks & Dependencies

| Risk | Mitigation |
|---|---|
| U1 cross-TZ math regression on same-tz fixtures | Same-tz scenarios from PR #3 retained as regression tests; new test_arrive_before_drops_late_arrivals + keeps_early continue to pass unchanged. |
| U5 broader filter accidentally drops valid award redemptions because cash side has times that no longer apply | Decision matrix above explicitly chooses `min(award_arr, cash_arr)` for safety, with rationale comment in code. |
| `logger.exception` introduces noise in environments running watchlists at high cadence | Log level is ERROR; consumers can filter via standard logging config. Doesn't change outcome.warnings flow. |

## Deferred to Follow-Up Work

- ce-code-review's `_browserbase.py` "premature abstraction" advisory (P1, owner human, not actionable) — plan U4 of the v0 sprint accepted this as wiring-ahead-of-consumer trade-off.
- `_signature` first-run alert storm advisory — intentional, documented in v0 plan U1.
- `fli` ratelimit serialization advisory — phase-2 work once Browserbase concurrency cap is real.
- PS-005 sync I/O in `_browserbase.get_session` async function — latent until Alaska's real implementation lands.
- AA / Delta Stagehand probe (`task #30` in tracker) — separate phase-2 gate.

## Sources & Research

- ce-code-review run artifact: `/tmp/compound-engineering/ce-code-review/20260607-200000-v0review/review.json` — findings #2, #3, #4, #9, #10.
- PR #3 body's "Residual Review Findings" section — duplicates the JSON's actionable subset.
- `docs/plans/2026-06-07-001-feat-points-redemption-v0-sprint-plan.md` — original v0 plan; U1, U3, U2 here build on U1, U3, U5 of that plan.

## Acceptance: Outcome the plan must enable

```
autopoints search LAX JFK 2026-06-14 --arrive-before 08:00ET --pax 1 --cabin economy
```

now returns a list where every visible redemption's earliest-known arrival (award or cash, whichever has populated time fields) is before 08:00 ET on 2026-06-15. Chart-floor redemptions whose cash baseline arrives later than 08:00 ET 2026-06-15 are dropped. Watchlist runner can recover from one watchlist's failure and continue. Persistent fli failures emit an operator-visible log line. Bad `--arrive-before` specs surface a clear "filter disabled" warning.
