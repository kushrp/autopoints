---
title: v2.a — Authenticated-session foundation (Aeroplan first)
type: feat
status: requirements
created: 2026-06-08
origin: none
---

# v2.a — Authenticated-session foundation (Aeroplan)

## Outcome

`autopoints search YYZ LHR 2026-10-15 --live-aeroplan` returns real Aeroplan award offers (not chart-floor estimates, not a 403, not a Kasada block) using a session captured from one Browserbase-driven login. Re-login on session expiry is fully automated when the AC account has TOTP enabled; otherwise it's a one-tap recovery via Discord slash command from a phone.

The architecture is built once for Aeroplan; v2.c will extract a `LoginAdapter` abstraction when AA gives us a second concrete example.

## Pre-v2.a probe (gates everything below)

Before any v2.a code lands, verify the hypothesis that an authenticated AC session clears the IAM `explicit deny` we hit in PR #9.

**Procedure (~1 hour):**
1. Log in to aircanada.com in normal Chrome.
2. Start an award flight search (YYZ → LHR or similar).
3. DevTools → Network → find the POST to `akamai-gw.dbaas.aircanada.com/loyalty/dapidynamicplus/.../air-bounds`.
4. Copy Request Headers: `Cookie`, `Authorization`, `x-api-key`, `ama-client-ref`, `ama-session-token`, and any other custom headers AC sends.
5. Hand-paste them into `AeroplanProvider._search_air_bounds()` as static values (replace the SigV4 path entirely for the probe).
6. Run `uv run autopoints search YYZ LHR 2026-10-15 --live-aeroplan` once.

**Outcomes:**
- **Real `AwardOffer` returned** → hypothesis verified. v2.a proceeds; the captured headers tell us exactly what the `SessionManager` needs to persist.
- **403 / `explicit deny`** → authenticated identity also rejected. Bigger problem; halt v2.a and rethink. Likely paths: scope to read-search-results-from-page-DOM (no API), use iOS app instead of web, or drop Aeroplan from scope.
- **Other failure** (e.g., header binding to a TLS fingerprint that httpx can't reproduce) → probe a Browserbase-resident request next: open a Browserbase session with the captured `storageState`, fire the request via `page.evaluate()` inside that session. If that works, v2.a's runtime model becomes "always search inside a live Browserbase context" instead of "extract headers and fire via httpx."

The probe outcome shapes the v2.a runtime model; do not skip it.

## Requirements

### R1 — `op` CLI integration (or 1Password Connect on NAS)

`autopoints` reads program credentials from 1Password at runtime:
- `op item get aeroplan --fields username,password` — login credentials
- `op item get aeroplan --otp` — TOTP code if AC TOTP is enabled

The same code path works against either the local `op` CLI (interactive devices) or 1Password Connect server (NAS). Detection is by env var: `OP_CONNECT_HOST` + `OP_CONNECT_TOKEN` → Connect; absence → local CLI. Missing both is a clean startup error, never a runtime surprise.

### R2 — Browserbase-driven login flow for Aeroplan

`autopoints login aeroplan` triggers a Browserbase session that:
1. Navigates to aircanada.com → sign in
2. Fills email + password from `op item get aeroplan --fields username,password`
3. Handles MFA: if `op item get aeroplan --otp` returns a code, fill the TOTP field; if not, post a Discord notification with a 5-minute wait window for the user to either run the slash command from phone or enter the email-MFA code (Discord bot accepts a DM reply with the code).
4. Waits for the post-login landing page.
5. Exports the full Playwright `storageState` (cookies + localStorage) plus any in-page tokens needed.
6. Encrypts and persists the captured blob (see R3).

The selectors are Aeroplan-specific and live in `autopoints/providers/aeroplan_login.py`. No abstraction yet — that's v2.c.

### R3 — Session blob persisted in 1Password secure note

One secure note per program titled `autopoints:session:aeroplan`. Body is a JSON document: `{captured_at, expires_at_hint, storage_state, additional_headers}`. Writing the note uses `op item edit` (or Connect equivalent); reading uses `op item get`.

The blob is treated as sensitive: any code path that logs it must redact. Plain-text persistence outside 1Password (e.g., a temp file) is forbidden.

### R4 — `SessionManager` for read / restore / detect-expiry

`autopoints/auth/session_manager.py` exposes:
- `SessionManager.get(program: str) -> Session | None` — read from 1Password, cache decrypted blob in process memory for the lifetime of the process.
- `SessionManager.invalidate(program: str)` — mark cache stale, force next `get()` to re-read from 1Password.
- `SessionManager.refresh(program: str) -> Session` — trigger the program's login flow, store the result.
- `Session.headers()` and `Session.cookies()` — render the blob into header dicts ready for httpx or Browserbase.

The runtime contract: a 401 / 403 / "session expired" response from a search means call `invalidate()`, call `refresh()` once, retry the search once. Second failure surfaces as a degraded result with a `warnings` entry, plus a Discord notification (R6).

### R5 — `AeroplanProvider` rewired

`AeroplanProvider.search()` reads the session from `SessionManager`, restores cookies + headers, fires `air-bounds` via httpx (or Browserbase page.evaluate, per probe outcome), parses the response with the existing parser. The `_get_cognito_credentials` / `_get_market_token` / SigV4 path is removed — that whole codepath was the architecture invalidated in PR #9.

Chart-floor fallback remains: if `SessionManager.get(aeroplan)` returns None, or refresh fails, the provider downgrades to chart-floor with a warning.

### R6 — Mobile re-login via Discord slash command

A Discord bot command `/autopoints login <program>` (restricted to the operator's Discord user ID) triggers `SessionManager.refresh(program)` on the NAS. The bot replies with the outcome:
- `✅ logged in, session cached until <expires_at_hint>` — happy path
- `🔄 awaiting MFA — DM me the email code or wait for TOTP` — MFA needs human input
- `❌ login failed: <reason>` — anything else; user can investigate

The slash command is the *only* mobile-reachable surface that performs authentication; the autopoints HTTP API is not exposed beyond the LAN.

### R7 — Anti-ban operational guardrails

The risk autopoints accepts is "AC notices my account is being automated and bans it." These are the hard rules that minimize that risk; they're enforced in `autopoints/providers/aeroplan.py`, not in policy comments:

- **Rate limit**: minimum 60 seconds between any two searches against Aeroplan. Enforced by an in-memory timestamp + sleep-until-allowed. The 60s clock is per-program, not global.
- **Jitter**: ±10 seconds randomized on the 60s minimum, so requests don't pattern-match an automated clock.
- **Daily cap**: max 100 Aeroplan searches per 24h rolling window (well above any actual usage, well below "looks like a bot"). Cap exceeded → next search is chart-floor + Discord warning.
- **Single concurrency**: at most one in-flight request to Aeroplan at any moment. Watchlist fan-out across multiple programs is fine; fan-out within Aeroplan is forbidden.
- **URL allowlist**: `AeroplanProvider` may only hit hosts/paths matching a hardcoded allowlist (Cognito endpoint, market-token endpoint, air-bounds endpoint, the auth.aircanada.com login pages). Any other URL raises a `ProviderError` at construction-time. This makes accidental booking-flow calls impossible to write.
- **Read-only enforcement**: the request method allowlist is `GET` and `POST` only against the URL allowlist above. No `PUT` / `DELETE` / `PATCH` is ever permitted in `AeroplanProvider`. The booking endpoints AC uses are different paths and would be allowlist-rejected; explicit method gating is a belt + suspenders.
- **Soft-warning auto-freeze**: if the response is 429, 403, redirects to a challenge page, or the body contains known "unusual activity" markers, `AeroplanProvider` enters a 24h frozen state — chart-floor fallback only — and posts a Discord alert. Frozen state is in 1Password (separate item) so it survives restarts.
- **Schedule-shape matching**: watchlist searches don't fire on exact-clock intervals. Default schedule is "between 09:00 and 22:00 in your local TZ, with ±15min jitter on each scheduled run." The watchlist runner enforces this; v2.a inherits without modification.
- **Hard "no booking" line**: `AeroplanProvider` has no code path that places, modifies, or cancels a reservation. The provider name is hardcoded in the URL allowlist regex to reject anything resembling a booking endpoint even if a future dev forgets the policy.

These rules are tested. Integration tests assert: 61-second gap between consecutive searches is rejected by rate limit, daily cap stops the 101st call, URL outside allowlist raises ProviderError, 429 response triggers auto-freeze + Discord post.

### R8 — NAS deployable from day one

v2.a runs on the NAS (the always-on target per STRATEGY.md). That means:
- `op` CLI alone is insufficient (no interactive session for `op signin`); 1Password Connect server must be installed on the NAS.
- Browserbase access uses the existing `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID` already configured.
- Discord bot uses the existing `discord` extra and `DISCORD_BOT_TOKEN` already configured per `live-checks.yml`.

1Password Connect setup is an operational task with its own checklist; the v2.a code must be Connect-aware (R1) but the setup itself is a `docs/ops/1password-connect-nas-setup.md` runbook, not a code unit.

## Actors

- **You (single user, operator)** — the only human in the system. Holds the AC account, the 1Password vault, the Discord channel, the NAS access.
- **autopoints daemon (NAS)** — runs watchlists, runs `SessionManager`, runs `AeroplanProvider`. Calls into 1Password Connect for credentials and Browserbase for login execution.
- **autopoints CLI / MCP client (laptop)** — interactive one-shot calls. Calls into 1Password CLI (not Connect) for credentials, into Browserbase for execution.
- **Discord bot** — proxy surface for mobile-driven re-login. Receives slash commands, dispatches them into the NAS daemon, reports outcomes.

## Key Flows

### F1 — First-time Aeroplan login (one-time setup)

1. User runs `autopoints login aeroplan` from laptop.
2. autopoints reads creds from local `op` CLI.
3. Browserbase session opens, navigates aircanada.com → sign-in.
4. Login flow fills username + password, handles TOTP via `op --otp` (or prompts user).
5. Post-login `storageState` is captured + written to 1Password secure note `autopoints:session:aeroplan`.
6. CLI prints `✅ Aeroplan session cached. Expires hint: <date>.`

### F2 — Routine search (cache hit)

1. `autopoints search YYZ LHR 2026-10-15 --live-aeroplan` (or watchlist runner triggers same code path).
2. Rate-limit gate checks: ≥60s since last Aeroplan call + within daily cap.
3. `SessionManager.get(aeroplan)` reads from 1Password (or in-process cache), restores cookies + headers.
4. `AeroplanProvider.search()` fires the request (httpx or Browserbase per probe outcome).
5. Response 200 → parse → return `AwardOffer` list.

### F3 — Session expired (silent re-login path)

1. Routine search returns 401 / 403 / session-expired marker.
2. `SessionManager.invalidate(aeroplan)`.
3. `SessionManager.refresh(aeroplan)` runs F1 again, headlessly (using `op --otp` for TOTP if available).
4. Original search retries once with new session → 200 → parse → return.
5. The whole event is logged but not Discord-notified (silent success).

### F4 — Session expired, TOTP not available (mobile-re-login path)

1. Routine search returns 401.
2. `SessionManager.refresh(aeroplan)` fails because TOTP isn't in 1Password and the login form needs it.
3. Discord bot posts: `⚠️ Aeroplan session expired; TOTP not configured. Reply with TOTP code or run /autopoints login aeroplan to retry.`
4. User on phone taps `/autopoints login aeroplan` slash command.
5. NAS-side bot triggers `SessionManager.refresh(aeroplan)` again — same code path as F3, but now interactively prompts the user via Discord DM if MFA needs input.
6. New session cached → bot replies `✅`. The search that triggered the expiry returns chart-floor for that one call; subsequent calls hit live.

### F5 — Anti-ban auto-freeze

1. Routine search returns 429 (or 403 with "unusual activity" body).
2. `AeroplanProvider` writes a frozen-state record into 1Password (separate item from session note).
3. Discord bot posts: `🛑 Aeroplan auto-frozen for 24h. Last response: <status, body snippet>. Investigate before re-enabling.`
4. All subsequent Aeroplan searches in the freeze window return chart-floor + warning.
5. After 24h, the freeze auto-expires. User can also manually unfreeze with `/autopoints unfreeze aeroplan` after investigating.

## Acceptance Examples

- **AE1** — Pre-v2.a probe with hand-pasted Chrome cookies returns ≥1 real `AwardOffer` for YYZ-LHR business. ✓ Hypothesis verified, v2.a proceeds. ✗ → halt and rethink.
- **AE2** — `autopoints login aeroplan` on laptop completes in <60 seconds (including TOTP), writes a session note to 1Password, then `autopoints search YYZ LHR 2026-10-15 --live-aeroplan` returns ≥1 real offer using the cached session.
- **AE3** — Two consecutive `autopoints search ... --live-aeroplan` calls fired 30 seconds apart: the second is delayed by the rate-limiter to ≥60s after the first. Verified by elapsed-wallclock assertion.
- **AE4** — Simulated 429 response from Aeroplan → `AeroplanProvider` enters frozen state, next 5 searches return chart-floor + warning, Discord receives a `🛑` post.
- **AE5** — Session cached, mark it expired manually in 1Password, run `autopoints search ... --live-aeroplan`: `SessionManager` detects 401, runs `refresh()` silently using TOTP from `op --otp`, search returns real offers within ~30 seconds total. No Discord notification.
- **AE6** — From phone Discord, `/autopoints login aeroplan` slash command triggers the NAS-side login flow, replies with `✅ logged in` or `🔄 awaiting MFA` within 60 seconds.
- **AE7** — `AeroplanProvider` constructed with a URL outside the hardcoded allowlist raises `ProviderError` at __init__ time, not at search time.

## Scope Boundaries

### Deferred for later

- **LoginAdapter abstraction** — extracted in v2.c when AA gives a second example. v2.a's code may be Aeroplan-shaped; that's the YAGNI bet.
- **AA / Delta / BA / JetBlue / VS** — those are v2.c through v2.g. Each will follow the v2.a pattern but with program-specific login modules.
- **Email-scraping for MFA fallback** — Gmail API integration to grab email-MFA codes automatically. Not worth the auth scope until a program forces our hand. Discord-DM-the-code is the v2.a fallback.
- **Live-endpoint canaries** — v2.b. v2.a relies on actual searches failing to detect breakage; canaries make that proactive but aren't blocking for v2.a.
- **MCP server wrapper** — v2.h. Once v2.a ships, the `--json` CLI surface is already MCP-shaped; wrapping is a separate work.

### Outside this product's identity

- **Automated booking.** v2.a is read-only by code (URL allowlist + method allowlist + hard line in `What we'll never do`). This is what keeps the legal posture defensible.
- **Multi-account rotation** for evading rate limits. One account per program; if AC bans the account, that program goes dark and we don't open a second.
- **Sharing captured sessions** between users. The session blob is in your 1Password vault, not in a shared vault, not in a public repo.

## Dependencies / Assumptions

- **Browserbase subscription** is in place and the API key works. (Already verified by v1.c-2 work; PR #9 e2e-browser passes.)
- **1Password subscription** is in place; user can create Connect server access tokens for NAS deployment. (User-confirmed.)
- **Aeroplan account** is in good standing. v2.a operates within that account, not against AC's policies in a way that would justify revocation under read-only personal use, but a pre-existing ban or "watch" status on the account would invalidate the architecture.
- **Discord bot** is already configured for the operator's user ID; slash command registration is a one-time setup.
- **NAS has `op` Connect server installable** — Connect runs as a Docker container with low resource footprint; this is expected to be straightforward.
- **AC's login flow remains a username/password (+ optional TOTP) page**, not (yet) a passkey-only flow. If AC moves to passkey-only, v2.a's login automation needs rethinking.

## Outstanding Questions

These are open at brainstorm exit and need to be resolved during planning or as the manual probe outcome lands:

- **Q1 — Is AC TOTP enabled on the account?** Yes → silent re-login via `op --otp` is the default fail-mode. No → Discord-DM-MFA is the default. User decision before planning. (Easy fix: enable TOTP on AC, store the secret in the 1Password item.)
- **Q2 — Probe outcome: do captured headers work in httpx, or only in a Browserbase context?** Determines whether `AeroplanProvider.search()` uses httpx (fast, ~5s) or page.evaluate inside Browserbase (slow, ~15s, per-search session lifecycle).
- **Q3 — Where does the rate-limit timestamp live during the process?** In-memory is sufficient for single-process; for multi-process (CLI + watchlist daemon both calling Aeroplan) it needs to be in SQLite or 1Password. v2.a probably picks SQLite for this.
- **Q4 — What's the session TTL hint we should encode?** AC doesn't surface session expiry in headers explicitly. Options: (a) trust until 401, (b) refresh proactively every N hours. (a) is simpler and surfaces ban-shaped issues sooner; (b) saves the cost of an expiry-detected re-login during interactive use.
- **Q5 — What's the 1Password Connect setup runbook for the NAS?** Docker compose snippet + access token rotation procedure. Not part of v2.a code but blocks production deployment; treated as `docs/ops/` work in parallel.

## Why this matters

v2.a is the architectural pivot that decides whether autopoints can offer "live award search for the programs you actually hold" at all. The anonymous-endpoint approach hit IAM walls (PR #9 evidence); authenticated sessions backed by real accounts are the only path that scales to every program (AA, Delta, BA, JetBlue, VS) with the same pattern, and the only path that un-drops Delta. Ship v2.a working for Aeroplan, and the rest of v2 is a multiplication exercise — same code shape, different login selectors.

If the pre-v2.a probe fails, the strategic claim "live coverage of the programs you hold" needs a third architectural attempt, and STRATEGY.md needs its third revision in three days. Run the probe first.
