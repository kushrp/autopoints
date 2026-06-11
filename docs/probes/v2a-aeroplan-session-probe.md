# v2.a pre-build probe: capture an authenticated Aeroplan session

**What we're testing:** does an authenticated Aeroplan session clear the
IAM `explicit deny` we hit in PR #9? The whole v2.a architecture is built
on this assumption; if it's wrong, we need a different approach before
writing any code.

**Time:** 15–30 minutes. Browser-driven, no engineering.

**Output:** one verdict from `scripts/probe_v2a_aeroplan_session.py` —
`PROBE_PASSES`, `PROBE_FAILS`, or `PROBE_INCONCLUSIVE` with guidance on
what to try next.

---

## Step 1 — Log in to Aeroplan in regular Chrome

Use your *normal* Chrome (the one logged into your Aeroplan account).
**Do not** use incognito — incognito creates a fresh unauthenticated
session, which is what we're trying to move away from.

Go to https://www.aircanada.com/ and confirm you see your account
indicator in the top-right. If you're not logged in, sign in now.

## Step 2 — Open DevTools and set up Network capture

1. Cmd+Option+I (macOS) / Ctrl+Shift+I (Windows/Linux) → DevTools.
2. Network tab.
3. Check **"Preserve log"** (so navigations don't clear history).
4. In the filter box, type `air-bounds` — this hides everything except
   the call we care about.

## Step 3 — Do a real award search

1. Navigate to https://www.aircanada.com/aeroplan/use-points/.
2. Start an award flight search:
   - From: **YYZ**
   - To: **LHR**
   - Departing: **2026-10-15** (or any future date)
   - Cabin: **Business**
   - 1 passenger
3. Click Search.
4. Wait for the results page to populate. You should see at least one
   POST to `akamai-gw.dbaas.aircanada.com/loyalty/dapidynamicplus/.../air-bounds`
   in the filtered Network panel, with status **200**.

If the status is 403, 429, or anything else, *that* is itself informative
— even your normal authenticated browser session is being blocked, which
means our v2.a assumption is wrong. Capture and run the probe anyway; the
script will classify whatever we get.

## Step 4 — Capture the request headers

1. Click on the `air-bounds` row in DevTools.
2. **Headers** tab → **Request Headers** subsection.
3. Right-click any header → "Copy all" (or manually copy each).

The headers that matter, in rough priority order:

- `Cookie` — the entire cookie blob. Long, contains many `key=value;` pairs.
  Includes the session ID, Kasada cookies, AC's own state. **Required.**
- `Authorization` — bearer token (`Bearer eyJ...`). Required for
  authenticated calls.
- `x-api-key` — should be `Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm` (or a
  rotated value).
- `ama-client-ref` — a UUID identifying the client session.
- `ama-session-token` — short-lived token from the market-token handshake.
- `Accept`, `Accept-Language`, `Content-Type` — standard, copy them.
- `User-Agent` — copy it (your real Chrome UA).
- `Referer` — should be the aeroplan booking page; copy it.
- Anything else starting with `ama-` or `x-` — copy it.

**Do not** copy `Host`, `Content-Length`, `Connection`, or any of the
`sec-fetch-*` headers — httpx sets those itself and copies of them confuse
the request.

## Step 5 — Write the headers as JSON

Create `/tmp/aeroplan-probe-headers.json` with this exact shape:

```json
{
  "Cookie": "everything from the cookie header verbatim",
  "Authorization": "Bearer eyJ...the whole thing...",
  "x-api-key": "Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm",
  "ama-client-ref": "uuid-from-devtools",
  "ama-session-token": "token-from-devtools",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "Content-Type": "application/json",
  "User-Agent": "Mozilla/5.0 ... (your real Chrome UA)",
  "Referer": "https://www.aircanada.com/aeroplan/use-points/"
}
```

`/tmp` is the right home for this — it's ephemeral, OS-cleaned, never
sync'd, never committed.

## Step 6 — Run the probe

```bash
cd /Users/kushrustagi/autopoints
uv run python scripts/probe_v2a_aeroplan_session.py
```

The script prints:
- Which header keys it loaded (values redacted)
- The HTTP status it got back
- A `PROBE_PASSES` / `PROBE_FAILS` / `PROBE_INCONCLUSIVE` verdict
- The first 500 chars of the response body for inspection

## Step 7 — Interpret the verdict

**`PROBE_PASSES`** (200 + non-empty `airBoundGroups`):
The hypothesis is real. v2.a proceeds — its job is to automate this
round-trip via Browserbase login + cached session in 1Password. Hand off
to `/ce-plan`.

**`PROBE_FAILS` (403 + explicit-deny)**:
The authenticated session ALSO doesn't have market-token permission. This
is bad news for v2.a. Likely paths forward:
- Inspect the rendered booking results page DOM instead of the API
- Use the Aeroplan iOS app (mitmproxy capture) which may have a different
  IAM role
- Drop Aeroplan from scope, route AC value via partner programs

**`PROBE_INCONCLUSIVE`** (anything else):
Read the verdict reason printed by the script. Most likely fixes:
- 429 → re-capture (your Kasada cookie was already stale)
- 401 → re-capture after a fresh login
- 200 with no offers → try a different date/cabin (saver availability
  varies)
- Non-JSON body → probably hit a Kasada interstitial; re-capture

## After the probe

Regardless of outcome, **delete the headers file** immediately when done:

```bash
rm /tmp/aeroplan-probe-headers.json
```

The captured cookies + JWT give read access to your AC account; treat
them with care while they exist.

Record the outcome (verdict + a sentence on what we learned) at the
bottom of this file under `## Run log` so future-you knows what was
tested when.

## Run log

_(Append `YYYY-MM-DD verdict — note` lines here after each probe run.)_
