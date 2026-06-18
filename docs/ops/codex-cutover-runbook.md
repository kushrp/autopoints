# Codex computer-use runbook: v2.a live cutover prep

Hand this file to a Codex computer-use agent (browser + terminal control) to complete the
three human-gated steps that unblock live Aeroplan award search. Work Tasks 1–3 in order.
Report findings as structured text; never paste secret values anywhere.

## Hard rules (do not violate)
- **Read-only.** Never click Book / Purchase / Confirm, never transfer points. Search and
  inspect only.
- **Never exfiltrate secrets.** When inspecting network headers, report only header
  **names** present and the HTTP **status**. Never output the **values** of `Cookie`,
  `Authorization`, `ama-session-token`, or any token/password.
- **Credentials come from 1Password only** (`op` CLI or the 1Password extension). Never
  type credentials from any other source; never echo them.
- **Stop and ask a human** if: MFA needs a code not in 1Password, a CAPTCHA / "unusual
  activity" wall appears, or any step would mutate an account.

## Task 1 — Aeroplan probe (browser + DevTools). The gating step.
1. Open Chrome (normal profile); go to `https://www.aircanada.com`; sign in to the
   Aeroplan account using 1Password item `aeroplan` (TOTP from 1Password if prompted; pause
   for the human if an email/SMS code is required).
2. DevTools (Cmd+Opt+I) → Network → check "Preserve log" → filter `air-bounds` → type
   Fetch/XHR.
3. Run an **award** search: YYZ → LHR, ~3 months out, one-way, redeem with points.
4. Click the POST whose URL contains `air-bounds` (host likely
   `akamai-gw.dbaas.aircanada.com`).
5. From Headers: record the **status code**; which of `Cookie`, `Authorization`,
   `x-api-key`, `ama-client-ref`, `ama-session-token` (+ any other `ama-*`/custom) are
   present (**names only**); whether the Response shows real award data.
6. Report: `status=<code>; headers present=<names>; response has award data=<yes/no>`.

> Outcome decides the runtime model: 200 + those headers → fire `air-bounds` via `httpx`
> with the captured session headers; fingerprint-bound → fire inside a live Browserbase
> browser instead.

## Task 2 — Environment setup (terminal).
1. `cd ~/Documents/autopoints && source .venv/bin/activate && python -c "from autopoints.auth.preflight import preflight; print(preflight().report())"`
2. Fix each MISSING line per `docs/ops/1password-connect-nas-setup.md`:
   - `op` missing → install + `op signin`.
   - Browserbase missing → export `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` (values
     from the human; do not print them).
   - Connect missing (NAS) → NAS-side 1Password Connect per the runbook; if NAS unreachable,
     note it and proceed (laptop `op` is enough for the first login).
3. Ensure a 1Password login item titled `aeroplan` exists (username, password, TOTP).
4. Re-run preflight; report the final OK/MISSING lines.

## Task 3 — Push the branch + open the PR (terminal).
1. `cd ~/Documents/autopoints && gh auth switch -u kushrp` (repo is `kushrp/autopoints`; the
   work account `kush-rogo` cannot push). If not configured, `gh auth login` (human
   completes browser auth).
2. `git push -u origin feat/v2a-plan-and-cpp-integration && gh pr create --fill`
3. Report the PR URL or the exact error.

## Final report format
```
TASK 1 (probe): status=<code>; headers present=<names>; response has award data=<yes/no>
TASK 2 (setup): <preflight final lines>; aeroplan 1P item=<created/exists/missing>
TASK 3 (push):  PR=<url or error>
```
No credential, cookie, token, or header value in the report.

## Scope note
Scoped to Aeroplan + local tooling only. Never touches banks (Chase/Amex/Citi) — they are
transfer sources, not award-search surfaces, and transfers stay human.
