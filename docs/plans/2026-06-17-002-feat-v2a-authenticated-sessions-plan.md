---
title: "feat: v2.a authenticated-session foundation (Aeroplan first) + token refresh"
type: feat
status: active
created: 2026-06-17
origin: docs/brainstorms/2026-06-08-v2a-authenticated-sessions-requirements.md
---

# feat: v2.a authenticated-session foundation + token refresh

**Target repo:** autopoints (kushrp/autopoints). Sequenced per `docs/STRATEGY.md` build
order (v2.a is the unblocker for AA/BA/Delta/JetBlue/VS). Read-only always; never book.

## Summary

Replace the invalidated anonymous-endpoint architecture (v1.c, 403'd by Air Canada's IAM)
with authenticated sessions. The user signs in once through a Browserbase-driven flow; the
session envelope is captured and persisted encrypted in 1Password; subsequent searches
reuse it; when it expires the system re-logs-in automatically using 1Password-held
credentials + TOTP, and only falls back to a human tap (Discord slash command) when MFA
genuinely needs a person. Aeroplan is the first and only concrete target here; the
`LoginAdapter` abstraction is extracted later at v2.c when AA provides a second example.

The three token-refresh mechanisms the user asked about are **one design, not
alternatives**:

1. **Sign in once, store the envelope.** A Browserbase login captures the Playwright
   `storageState` (cookies + localStorage + bound tokens) — the reusable session.
2. **1Password as the credential + TOTP source.** Re-login is automated because
   `op item get aeroplan --fields username,password` and `op item get aeroplan --otp`
   supply everything the login flow needs without a human.
3. **Graceful auto-refresh so you rarely intervene.** A 401/403/expired response triggers
   invalidate → refresh-once → retry. If refresh needs human MFA, a Discord slash command
   is the only manual surface; otherwise everything stays automatic, and chart-floor is the
   always-available fallback when a session is cold.

## Problem Frame

v1.c shipped a Browserbase Kasada bypass and an auto-minted *anonymous* Cognito identity,
but live testing proved both dead ends: the in-page `window.fetch` to
`akamai-gw.dbaas.aircanada.com` is blocked by Dynatrace RUM + Kasada before leaving the
page, and the anonymous identity is 403-denied at the market-token resource by AC's IAM
policy. The shipped v1.c code stays in the tree as scaffolding for the login flow. The fix
is to operate *inside* the auth boundary the airline already permits: a logged-in session.
This is the AwardWiz pattern — which died of fingerprint detection, not auth attrition, so
Browserbase stealth handles the part that killed it.

---

## Step 0 — Gating manual probe (HUMAN, ~1hr, not agent-executed)

No v2.a code lands until this verifies that an authenticated AC session clears the IAM
deny. **This is a human step** (real aircanada.com login + DevTools); the agent cannot and
must not perform it.

Procedure: log in to aircanada.com in normal Chrome, start an award search (e.g. YYZ→LHR),
DevTools → Network → find the POST to `.../air-bounds`, copy the request headers (`Cookie`,
`Authorization`, `x-api-key`, `ama-client-ref`, `ama-session-token`, plus any custom
headers), hand-paste them as static values into `AeroplanProvider._search_air_bounds()`
(replacing the SigV4 path for the probe), and run one `--live-aeroplan` search.

Outcomes decide the runtime model:
- **Real `AwardOffer`** → hypothesis verified; the captured headers define exactly what
  `SessionManager` must persist. Proceed.
- **403 / explicit deny** → authenticated identity also rejected. Halt v2.a; fall back to
  reading results from the page DOM, the iOS app, or dropping Aeroplan.
- **Other (e.g. TLS-fingerprint binding httpx can't reproduce)** → switch the runtime model
  to "fire the request inside a live Browserbase context via `page.evaluate()`" instead of
  extracting headers and calling via httpx.

---

## Key Technical Decisions

- **Session, not endpoint.** Persist a logged-in `storageState` envelope and reuse it.
  Removes the entire Cognito/SigV4/market-token codepath invalidated in PR #9.
- **1Password is the only credential store.** No plaintext, no env vars for creds. Local
  `op` CLI on laptops; 1Password Connect on the NAS (detected via `OP_CONNECT_HOST`).
- **Refresh is automatic first, human last.** Auto re-login via stored creds + TOTP; the
  Discord slash command exists only for the email-MFA / failure path.
- **Chart-floor is the safety net.** A cold or failed session degrades to chart-floor with
  a warning, never a hard failure. Live is honest about being live; chart-floor about being
  a floor.
- **One concrete adapter now.** Aeroplan selectors live in `aeroplan_login.py`; the
  `LoginAdapter` abstraction is extracted at v2.c (AA) when there is a second example.
- **$0/mo recurring.** Browserbase + 1Password are already held. No new paid bypass
  services (per STRATEGY.md "what we'll never do").

---

## Implementation Units

### U1. `op` (1Password) credential + TOTP access

**Goal:** Read program credentials and TOTP from 1Password at runtime, local CLI or Connect.

**Files:** `autopoints/auth/op_client.py`, `tests/test_op_client.py`

**Approach:** Wrap `op item get <program> --fields username,password` and `--otp`. Detect
Connect via `OP_CONNECT_HOST` + `OP_CONNECT_TOKEN`; otherwise local CLI. Missing both is a
clean startup error, never a runtime surprise. Mockable subprocess/Connect boundary.

**Test scenarios:**
- Happy: returns username/password and a 6-digit OTP for a configured item (mocked `op`).
- Edge: neither local `op` nor Connect env present → explicit startup error.
- Error: `op` non-zero exit → typed error, secrets never logged.

**Verification:** unit tests pass with a mocked `op`/Connect boundary.

### U2. `SessionManager` (get / invalidate / refresh)

**Goal:** Own session lifecycle backed by 1Password.

**Requirements:** R4

**Dependencies:** U1, U3 (storage)

**Files:** `autopoints/auth/session_manager.py`, `tests/test_session_manager.py`

**Approach:** `get(program)` reads the encrypted blob from 1Password, caches the decrypted
session in process memory. `invalidate(program)` clears the cache. `refresh(program)`
triggers the login flow and stores the result. `Session.headers()` / `Session.cookies()`
render the blob for httpx or Browserbase. Runtime contract: a 401/403/expired from a search
→ `invalidate` → `refresh` once → retry once; second failure → degraded result + warning +
Discord notification.

**Test scenarios:**
- Happy: `get` returns a cached session after first read; second `get` does not re-read 1P.
- Refresh: `invalidate` then `get` re-reads from 1P.
- Contract: simulated 401 triggers exactly one refresh+retry; a second 401 degrades, does
  not loop.

**Verification:** lifecycle tests pass; no real network.

### U3. Session blob persisted in a 1Password secure note

**Goal:** Durable, encrypted session storage.

**Requirements:** R3

**Dependencies:** U1

**Files:** `autopoints/auth/session_store.py`, `tests/test_session_store.py`

**Approach:** One secure note per program titled `autopoints:session:<program>`, body JSON
`{captured_at, expires_at_hint, storage_state, additional_headers}`. Write via `op item edit`
(or Connect); read via `op item get`. Any code path that logs the blob must redact.
Plaintext persistence outside 1Password is forbidden.

**Test scenarios:**
- Happy: round-trip write→read returns the same envelope (mocked `op`).
- Security: a logging helper redacts `storage_state` and `additional_headers`.

**Verification:** round-trip + redaction tests pass.

### U4. Browserbase-driven Aeroplan login flow

**Goal:** One login captures the session envelope.

**Requirements:** R2

**Dependencies:** U1, U3

**Files:** `autopoints/providers/aeroplan_login.py`, `tests/test_aeroplan_login.py`

**Approach:** `autopoints login aeroplan` opens a Browserbase session → aircanada.com sign-in
→ fills creds from `op` → handles MFA (TOTP from `op --otp`; else Discord notification with a
5-minute wait for a phone slash-command or DM'd email code) → waits for post-login landing →
exports Playwright `storageState` + in-page tokens → persists via U3. Aeroplan-specific
selectors only; no abstraction yet.

**Test scenarios:**
- Happy: a mocked Browserbase driver returning a known landing state yields a stored
  envelope.
- MFA-TOTP: OTP present → filled automatically, no Discord prompt.
- MFA-human: OTP absent → Discord notification fired; flow waits then resumes on code.

**Verification:** flow unit-tested against a mocked Browserbase driver.

### U5. `AeroplanProvider` rewired to sessions + R7 guardrails

**Goal:** Live Aeroplan search via the stored session, with hard anti-ban rules.

**Requirements:** R5, R7

**Dependencies:** U2, U4

**Files:** `autopoints/providers/aeroplan.py`, `tests/test_aeroplan.py` (extend)

**Approach:** `search()` reads the session from `SessionManager`, restores cookies+headers,
fires `air-bounds` via httpx (or Browserbase `page.evaluate` per the step-0 probe outcome),
parses with the existing parser. Remove the Cognito/market-token/SigV4 path. Chart-floor
fallback when no session or refresh fails. Enforce R7 in code (not comments): 60s + jitter
between searches (per-program), daily cap 100/24h rolling, single concurrency, URL
allowlist (Cognito/market-token/air-bounds/login hosts only — anything else raises
`ProviderError` at construction), GET/POST-only method gate, auto-freeze 24h on
429/403/challenge/"unusual activity" markers (freeze state stored in a separate 1P item so
it survives restarts).

**Test scenarios:**
- Guardrail: a 61s-gap second search is rate-limit-rejected; the 101st daily call →
  chart-floor + warning.
- Guardrail: a URL outside the allowlist raises `ProviderError`; a `PUT`/`DELETE` is
  rejected.
- Guardrail: a 429 response triggers 24h auto-freeze + Discord post; frozen state persists.
- Happy: a valid session + mocked air-bounds response yields parsed `AwardOffer`s.
- Fallback: no session → chart-floor with the "not confirmed" note.

**Verification:** guardrail + parse tests pass; no real AC network in CI.

### U6. Discord re-login slash command

**Goal:** The single mobile-reachable manual re-login surface.

**Requirements:** R6

**Dependencies:** U2

**Files:** `autopoints/discord_bot/bot.py` (extend), `tests/test_discord_relogin.py`

**Approach:** `/autopoints login <program>` (restricted to the operator's Discord user ID)
calls `SessionManager.refresh` on the NAS and replies with the outcome (✅ cached until
`<hint>`, 🔄 awaiting MFA, ❌ failed). The autopoints HTTP API stays LAN-only; this is the
only auth surface reachable from a phone.

**Test scenarios:**
- Happy: authorized user → refresh invoked, success reply.
- AuthZ: non-operator user → command refused.
- MFA: refresh needs MFA → "awaiting MFA" reply, accepts a DM'd code.

**Verification:** command handler tests pass with a mocked SessionManager.

### U7. NAS deployability (1Password Connect-aware) + canary note

**Goal:** v2.a runs on the always-on NAS target.

**Requirements:** R8

**Dependencies:** U1

**Files:** `docs/ops/1password-connect-nas-setup.md`, config wiring in `autopoints/config.py`

**Approach:** Code is Connect-aware via env detection (U1). The Connect server install is an
operational runbook, not a code unit. Note the v2.b live-endpoint canary (nightly synthetic
search per live provider, alert on failure) as the immediate follow-on that catches session
expiry / anti-bot escalation before silent failures.

**Test scenarios:** Test expectation: none -- ops runbook + config plumbing covered by U1.

**Verification:** runbook exists; config resolves Connect vs local correctly (covered in U1).

---

## Scope Boundaries

### Deferred to Follow-Up Work
- v2.b live-endpoint canaries.
- v2.c AA via authenticated session — the point at which `LoginAdapter` is extracted.
- v2.d/e/f/g BA, Delta (1Password TOTP un-drops it), JetBlue, Virgin Atlantic.
- v2.h MCP server wrapper; v2.i stale-availability re-verifier.

### Out of scope (per STRATEGY.md)
- Booking automation. Sessions are read-only: search, availability, balance only.
- Paid anti-bot bypass services beyond Browserbase.
- seats.aero or any commercial-aggregator dependency.
- Multi-tenant / public-facing deployment.
