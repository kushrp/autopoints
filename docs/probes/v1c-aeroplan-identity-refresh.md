# How to capture a fresh Aeroplan Cognito IdentityId

**Why:** the IdentityId hardcoded in `autopoints/providers/aeroplan.py`
(`us-east-2:7f9c31d7-d242-4f7e-afda-916b8c6c2b9c`) was revoked by Air Canada.
The live-checks harness (`scripts/check_live.py`) reports HTTP 403 with
"explicit deny in an identity-based policy" from the market-token endpoint
on every run. This is real signal: the handshake is correct, but the
identity itself is dead. We need to re-discover the current IdentityId
that aircanada.com's web client is using.

**Time:** 15–30 minutes. No engineering needed — just open DevTools, do a
flight search, copy a string.

---

## Easiest path: Chrome DevTools (recommended)

You don't need mitmproxy or Charles for this — Chrome's built-in DevTools
captures the same requests because aircanada.com's web client makes them
client-side. The page is Kasada-protected but the Kasada challenge only
gates *outgoing* requests, not what's visible in DevTools.

### Steps

1. **Open a private/incognito Chrome window.** This avoids interference
   from any prior aeroplan.com cookies and ensures the Cognito identity
   you see is the one a fresh-state visitor gets.

2. **Open DevTools → Network tab.** Cmd+Option+I on macOS, Ctrl+Shift+I
   on Windows/Linux. Click "Network", then check the **"Preserve log"**
   checkbox so events from the initial page load don't get cleared when
   the search page navigates.

3. **Filter to XHR:** in the Network filter box, type `cognito` (without
   quotes). This narrows results to just the AWS Cognito call we care
   about.

4. **Navigate to https://www.aircanada.com/** and dismiss any cookie
   banner. You may need to wait 3–5 seconds while Kasada solves its
   challenge in the background — that's fine, we don't need to interact
   with it.

5. **Start an award flight search.** Use any route — JFK → YYZ, LAX →
   YVR, whatever. Click "Book" → toggle "Use points" → enter origin /
   destination / a future date → click "Search".

   The act of starting the search triggers the Cognito identity exchange.

6. **Look for the Cognito request in the Network panel.** You should see
   a row with URL `https://cognito-identity.us-east-2.amazonaws.com/`,
   method POST, status 200. If you see it as 403, the page hasn't
   finished its handshake — wait a moment and try again.

7. **Click on that Cognito row** to open its details. Go to the
   **Payload** tab (or "Request" depending on Chrome version). You'll
   see JSON like:

   ```json
   {
     "IdentityId": "us-east-2:XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
   }
   ```

   The `IdentityId` value is what we need. Copy the entire
   `us-east-2:...` string (including the `us-east-2:` prefix).

8. **Paste it into `autopoints/providers/aeroplan.py`:**

   ```python
   _COGNITO_IDENTITY_ID = "us-east-2:NEW_VALUE_HERE"
   ```

   Replace the old value at the top of the file. Commit and push.

9. **Re-run the live check** to verify:

   ```bash
   uv run python scripts/check_live.py --only aeroplan_handshake_reaches_air_bounds
   ```

   Expected outcome: the error message changes from "explicit deny in
   identity-based policy" to "Kasada" (HTTP 429). Kasada is the expected
   block at this layer — v1.c-2 will route around it via Browserbase.

---

## Fallback: mitmproxy iOS capture

If the Chrome DevTools approach doesn't expose a fresh `IdentityId` (e.g.,
Air Canada moves the Cognito call into a web worker that's hard to
inspect, or starts pinning the request to a per-page token), fall back to
the iOS Aeroplan app via mitmproxy. The flow mirrors the BA mitmproxy
approach in
[`v1b-ba-mitmproxy-approach.md`](v1b-ba-mitmproxy-approach.md):

1. Install mitmproxy locally, route iPhone Wi-Fi through it.
2. Trust the mitmproxy CA on iOS (Settings → General → VPN & Device
   Management).
3. Open the Aeroplan iOS app, do an award search.
4. Look for the POST to `cognito-identity.us-east-2.amazonaws.com/` in
   mitmproxy's flow list.
5. Copy the `IdentityId` from the request payload.

The iOS app likely uses the same identity pool as the web client, so
either source should produce a working value. Use the web path first
since it's faster.

---

## What to do once the IdentityId is updated

- Commit the change with `fix(aeroplan): refresh Cognito IdentityId (revoked
  by AC IAM)` so the history records why the value changed.
- Don't worry about the actual value being secret — Cognito identity pool
  IDs are designed to be exposed in client code. The IAM policy attached
  to the unauthenticated identity role is what restricts what the
  identity can do.
- If a future refresh shows the IdentityId rotates frequently (e.g.,
  monthly), consider scraping it from a live page load instead of
  hardcoding. That's a v1.c-3 task; today, hardcode and refresh as
  needed.

---

## Why this was needed

The original IdentityId in `aeroplan.py` came from `xmsley614/nt_tool`
(2023 commit) and was working as recently as the `RiskByPass/riskbypass_demo`
commit on 2026-06-05. The live-checks harness (`scripts/check_live.py`)
first ran against this endpoint on 2026-06-08 and saw the 403 — meaning
either:

- AC rotated the unauthenticated identity pool sometime in the last week, or
- Multiple public scrapers caused AC to revoke the specific IdentityId
  the scrapers shared (highly likely; the seats.aero v. AC lawsuit page
  references "API scraping").

Either way, the fix is the same: capture a fresh value from a live page
load. Recurring refreshes are unfortunate but cheap.
