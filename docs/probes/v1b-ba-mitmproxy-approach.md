# v1.b spike: BA Avios iOS app — mitmproxy capture approach

**Status: executable plan.** The 2015 `ba_rewards` endpoint is dead (NXDOMAIN confirmed,
maintainer archived). This document is a concrete, step-by-step approach for rediscovering
the modern BA Avios Flight Finder API via iOS traffic capture. Complete this spike before
writing any Python code in `autopoints/providers/british_airways.py`.

Estimated spike duration: 4–8 person-hours (see §3 for breakdown).

---

## 1. Mitmproxy capture procedure

### 1.1 Install mitmproxy

```bash
brew install mitmproxy   # macOS — installs mitmproxy, mitmdump, mitmweb
mitmproxy --version      # verify: 10.x or later
```

Alternatively, Charles Proxy (macOS GUI, $50 licence) works and may be easier to
bookmark individual requests for later review. Either tool is fine; this doc uses
mitmproxy vocabulary.

### 1.2 Start the proxy

```bash
mitmweb --listen-port 8080   # opens browser UI at http://127.0.0.1:8081
```

Note your Mac's LAN IP: `ipconfig getifaddr en0` (or check System Settings > Wi-Fi >
Details). Call it `$PROXY_IP`.

### 1.3 Route iPhone traffic through the proxy

1. Connect iPhone to the same Wi-Fi network as the Mac.
2. Settings > Wi-Fi > tap (i) next to the SSID > Configure Proxy > Manual.
3. Server: `$PROXY_IP`, Port: `8080`. Save.
4. Open **Safari** (not Chrome) and navigate to `http://mitm.it`.
5. Tap the green "iOS" button. Allow the profile download.
6. Settings > General > VPN & Device Management > mitmproxy > Install.
7. Settings > General > About > Certificate Trust Settings > enable the mitmproxy toggle.

iOS 17/18 note: the trust toggle is in "Certificate Trust Settings", not in the profile
install screen. If traffic still doesn't appear after install, toggle Airplane Mode off/on
to force the Wi-Fi re-attach.

### 1.4 Install the BA app and search for flights

Install the British Airways app from the App Store (current version as of mid-2026).
With the proxy active and mitmweb open:

1. Launch the BA app and sign in to your Executive Club account.
   - The login flow itself is worth capturing: it will reveal the auth endpoint (OAuth2
     token, Cognito, or proprietary SSO — see §2.2 below).
2. Navigate to "Avios" or "Reward Flights" in the app's bottom nav.
3. Run a search you know has award inventory:
   - **LHR → JFK**, Economy, 6–9 months out (BA transatlantic longhaul has consistent
     award space).
   - **LHR → DXB**, Business, same window.
   - Run both so you get responses for at least two cabin classes and two route types.
4. If the results page loads a calendar (date grid with Avios prices per day), tap one
   specific date to load per-flight detail. That second tap likely triggers a separate
   detail endpoint — capture both.

### 1.5 Bookmark and export the relevant requests

In mitmweb (`http://127.0.0.1:8081`):

- Filter by `~h Host ~ba.com OR ~h britishairways OR ~h iagloyalty` to narrow to BA
  traffic and exclude analytics noise.
- Bookmark (star) every request whose URL path contains words like `avios`, `reward`,
  `award`, `availability`, `search`, `flight`, or `offer`.
- Export each bookmarked flow: Flow > Export > curl command. Paste into a scratch file;
  you will replay these with `curl` after disabling the proxy.

```bash
# Example replay after proxy is off (to confirm reproducibility):
curl -s '<pasted curl command from mitmweb>' | python3 -m json.tool | head -60
```

---

## 2. What to look for in the capture

### 2.1 Probable request shape

The 2015 endpoint used:

```
GET /departure/cities/{O}/destination/{D}?cabinClass=E&sc=X&obDate=DDMMYYYY
```

The modern iOS app almost certainly does not use the same hostname (`bitnamiapp.com` is
gone). Probable modern candidates based on BA's public infrastructure:

- `api.britishairways.com/...`
- `loyalty.ba.com/...` or `aem.britishairways.com/...`
- `gateway.iairgroup.com/...` (IAG-level API gateway shared with Iberia/Vueling)

The path structure and query-param vocabulary are likely to have evolved. Look for:

| 2015 parameter | Modern equivalent (probable) |
|----------------|------------------------------|
| `cabinClass=E/P/B/F` | same letter codes, or full word `economy` |
| `sc=X/P/U/Z` | same booking-class bucket letters |
| `obDate=DDMMYYYY` | or ISO `departureDate=YYYY-MM-DD` |
| route via path segments | or query params `origin=LHR&destination=JFK` |

The response key space (`cityName`, `prices.rfs`, `prices.prices.A`, `out[].d`,
`out[].bs`) may be significantly restructured — treat the 2015 contract as a reference
shape only. Capture the raw JSON before trying to map it.

### 2.2 Auth headers to capture

Unlike the 2015 open dev server, the modern stack will require auth. Look for:

- **Bearer token** in `Authorization: Bearer <jwt>` — the most common pattern for
  airline loyalty APIs. The JWT is typically obtained from a prior `/oauth/token` or
  `/auth/login` call using EC credentials.
- **API key** in `x-api-key` or `x-client-id` — seen on the IAG developer portal and
  on the Aeroplan stack (`x-api-key: Z5R8Rm1sA...` — see `v1c-aeroplan-endpoint-discovery.md`).
- **Market token** — a short-lived per-session token fetched after login and passed in
  a custom header (similar to Aeroplan's `x-market-language` + per-request signed token).
- **Akamai sensor data** — if Akamai Bot Manager is active, look for `_abck` cookie and
  an `x-akamai-config-log` or sensor-data header. These are dynamic and session-bound;
  they cannot be replayed naively.

Capture the **full login sequence** first (from app open through the home screen), not
just the search call. The auth token you need is issued earlier in that flow.

### 2.3 Cert pinning — what to do if mitmproxy shows CONNECT errors

If the BA app uses TLS cert pinning, mitmweb will show the request as a CONNECT tunnel
with no decrypted body, and the app may show a network error. Signs:

- mitmproxy shows `SSL handshake error` or `Client TLS handshake failed` for BA hosts.
- The app shows a "Connection error" that only happens when the proxy is active.

**Bypass options, in order of effort:**

**Option A — Frida Gadget injection (no jailbreak required, ~2h)**

1. Obtain the BA IPA from a legitimate source (your own purchase, or export from a
   device you own using a tool like iMazing).
2. Inject Frida Gadget into the IPA binary:
   ```bash
   pip install objection
   objection patchipa --source BA.ipa --codesign-signature <your-apple-dev-team-id>
   ```
3. Sideload the patched IPA via Xcode or AltStore.
4. Connect Frida: `frida -U -n "British Airways" -l ios-ssl-kill-switch.js`
   (use the `ios-ssl-pinning-bypass.js` from the `frida-scripts` community repo).
5. Re-run the mitmproxy capture with the proxy active.

Frida Gadget works on iOS 16–18 without a jailbreak as long as you can re-sign the IPA.
Objection automates the injection step. The limitation: if BA uses a custom TLS stack
(BoringSSL compiled in, rather than Apple's `SecTrust` APIs), standard Frida SSL scripts
may not hook the right function and you will need a custom script targeting the
specific symbol.

**Option B — iOS Simulator (fastest, ~30min, often works)**

The iOS Simulator does not enforce cert pinning at the OS level. If the BA app has an
ARM64 simulator slice (less common for shipping apps), sideload it in the simulator and
run mitmproxy capture there. Most airline apps ship device-only binaries, making this
unlikely to work — but worth a 10-minute check before investing in Option A.

**Option C — Jailbroken device + SSL Kill Switch 2 (~4h setup if device not already jailbroken)**

On a jailbroken device (checkra1n or palera1n on A11 or earlier), install SSL Kill Switch 2
via Cydia. Toggle "Disable SSL Certificate Validation" in Settings. This globally patches
`SecTrustEvaluate` and defeats most pinning implementations. Highest reliability but
requires a compatible device on a supported iOS version (iOS 15.x on A11 is the most
stable jailbreak surface as of 2025).

**Option D — Capture ba.com web client instead (fallback, see §3.4)**

The ba.com Reward Flight Finder at `https://www.britishairways.com/travel/flightfinder/`
talks to the same or a closely related backend without iOS cert pinning. Akamai WAF
is still present, but a browser-based capture (via mitmproxy configured as a system
proxy or using Chrome DevTools > Network) gets you the request shape without any
pinning fight.

---

## 3. Risk assessment

### 3.1 Cert pinning probability

**High (~85%).** Every major airline app as of 2024–2025 pins TLS. British Airways
underwent a significant app security overhaul following the 2018 ICO breach (£20M fine).
The rebuilt app almost certainly implements pinning via `TrustKit`, Apple's built-in
`NSPinnedDomains` plist approach (iOS 14+), or a custom implementation. Plan for Option A
(Frida Gadget) as the default path.

### 3.2 TLS fingerprinting at the Akamai layer

**High probability (~75%).** BA's Akamai configuration uses Bot Manager (confirmed by the
`_abck` cookie presence on `ba.com`). Akamai Bot Manager scores requests based on
JA3/JA4 TLS fingerprints, HTTP/2 SETTINGS frame ordering, and behavioral signals.

A raw `httpx` or `requests` client will produce a Python-shaped TLS fingerprint
(`JA3 ≈ 769,47-53-5-10-49161-49162-...`) that Akamai flags immediately. Mitigation:

- Use `curl_cffi` with `impersonate="chrome131"` (or the latest Chrome fingerprint) to
  match browser JA3/JA4. This is the same mitigation as the Aeroplan path.
- The iOS app's TLS fingerprint (captured by mitmproxy before the handshake) is the
  ground truth — note the TLS version, cipher suite list, extension ordering, and ALPN
  from the raw CONNECT log. Replaying with matching fingerprint is more reliable than
  impersonating Chrome.
- Even with correct TLS fingerprint, Akamai's `_abck` sensor cookie requires a valid
  JS challenge solution. For programmatic use, `curl_cffi` + a solved `_abck` (stolen
  from a real browser session during capture) often holds for 5–15 minutes before
  invalidation.

### 3.3 Estimated person-hours

| Phase | Hours |
|-------|-------|
| mitmproxy install + iOS proxy setup | 0.5 |
| Initial capture (no pinning) | 0.5 |
| Cert pinning fight via Frida Gadget | 1.5–3.0 |
| Request analysis + JSON schema mapping | 1.0 |
| Porting to `british_airways.py` + tests | 2.0–3.0 |
| **Total (optimistic)** | **5.5h** |
| **Total (pessimistic, pinning hard)** | **8h** |

If pinning requires a jailbroken device (Option C) that needs to be sourced or set up,
add 3–6h for device preparation. Factor in before committing the spike to a sprint.

### 3.4 Worst-case fallback: ba.com web client capture

If the iOS app is fully locked down (custom TLS stack, aggressive jailbreak detection,
Frida detection), pivot to capturing ba.com's browser-side award search. The Reward
Flight Finder at `https://www.britishairways.com/travel/flightfinder/public/en_gb`
is JavaScript-rendered but its network calls are visible in Chrome DevTools (Network tab,
filter: `XHR`/`Fetch`). No cert pinning. Akamai WAF is still present, but:

- The first capture can be done with no automation tooling — just open DevTools and
  search for a flight.
- Replaying the captured `curl` command works for ~10–15min before the session token
  expires.
- The API host and path are the same backend the iOS app talks to; only the auth
  token source differs (browser session cookie vs. mobile OAuth token).
- Downside: the web client uses a `__utmz`/`_abck` session that is harder to obtain
  programmatically than a mobile Bearer token.

---

## 4. Concrete next actions

1. **Install mitmproxy.** `brew install mitmproxy`. Verify `mitmweb --version`.
2. **Configure iOS proxy.** Wi-Fi > Manual proxy at `$PROXY_IP:8080`. Install and trust
   the mitmproxy CA cert via `http://mitm.it` in Safari.
3. **Test with a non-pinned app first.** Open Safari on the iPhone and navigate to
   `https://example.com`. Confirm the request appears in mitmweb. This validates proxy
   setup before touching the BA app.
4. **Launch the BA app with proxy active.** Observe mitmweb. If you see decrypted BA
   traffic: proceed to step 6. If you see `SSL handshake error` for BA hosts: proceed
   to step 5.
5. **Defeat cert pinning via Frida Gadget.**
   - Export BA IPA from a device you own (iMazing > Manage Apps > export IPA).
   - `pip install objection` in a fresh venv.
   - `objection patchipa --source BritishAirways.ipa --codesign-signature <TEAM_ID>`
   - Sideload patched IPA via `ios-deploy` or AltStore.
   - `frida -U -n "British Airways" -l frida-scripts/ios-ssl-pinning-bypass.js`
   - Re-activate the mitmproxy proxy on the device. Relaunch the BA app.
6. **Run a known-good award search.** In the BA app: Avios > Reward Flights >
   LHR → JFK, Economy, pick a date 6+ months out. Tap Search.
7. **Bookmark the search request.** In mitmweb, star the request to the BA backend that
   returns the availability JSON. Note the full URL (host + path + params), all request
   headers, and the response body shape.
8. **Trigger the per-flight detail call.** Tap a specific date in the result calendar.
   Bookmark that second request. This is likely the endpoint that returns flight times,
   carrier, and flight numbers — data the 2015 gem never captured.
9. **Export both requests as curl commands.** mitmweb: Flow > Export > curl command.
   Paste both into `docs/probes/v1b-ba-captured-requests.sh` (gitignore'd).
10. **Disable the proxy on the device** and replay the curl commands from the Mac.
    Confirm you get a `200` with the expected JSON. If you get `403` or `429` (Akamai
    challenge): note the `_abck` cookie and `x-akamai-bm-telemetry` header in the
    captured request; include those exact values in the replay.
11. **Map the JSON response** to the `AwardOffer` fields in `autopoints/search/models.py`.
    Write this mapping in a comment block at the top of `british_airways.py` before any
    code.
12. **Port to Python.** Implement `BritishAirwaysProvider` following the pattern in
    `autopoints/providers/aeroplan.py`. Use `curl_cffi` with
    `impersonate="chrome131"` if TLS fingerprinting is required (swap `httpx.AsyncClient`
    for `curl_cffi.requests.AsyncSession`).
13. **Write unit tests.** Use `respx` (or `pytest-httpx`) to mock the captured response
    body. Add an `@pytest.mark.e2e` test that runs against the live endpoint only when
    `BA_LIVE_ENDPOINT` env var is set.
14. **Gate behind feature flag.** Wire `BritishAirwaysProvider` in `autopoints/search/build.py`
    behind `BuildOptions.use_live_ba = False` (default off) until the endpoint is
    confirmed stable across multiple days.
15. **AwardOffer returned.** Milestone complete when the e2e test passes: LHR→JFK,
    `cabin=economy`, 6 months out, ≥1 `AwardOffer` returned with `points > 0`.

---

## 5. What NOT to do

- **Do not hit `dev1-flightavail-avios.bitnamiapp.com`.** NXDOMAIN. The domain is gone.
  Any code targeting this host will time out immediately.
- **Do not try the 2015 path on `api.britishairways.com`.** The path
  `/departure/cities/{O}/destination/{D}` was served from a Bitnami dev server, not from
  BA's production API gateway. Even if you find the right hostname, the 2015 path
  almost certainly returns 404 on the modern stack.
- **Do not scrape the ba.com booking widget JSON as a primary approach.** The booking
  flow at `britishairways.com/travel/book/...` is heavily WAF'd, requires a browser
  session with solved Akamai JS challenges and a CSRF token, and returns booking-flow
  HTML rather than clean award-availability JSON. This is a last-resort fallback
  (see §3.4), not a primary strategy.
- **Do not use `httpx` or `requests` as the HTTP client without TLS fingerprint spoofing.**
  Akamai will fingerprint the Python TLS hello and rate-limit or block within a few
  requests. Start with `curl_cffi` if TLS fingerprinting is confirmed in the capture.
- **Do not assume the response shape matches the 2015 gem's JSON keys.** `prices.prices.A`,
  `out[].d`, `out[].bs` are inferred from 11-year-old Ruby. The modern response almost
  certainly uses different key names (possibly camelCase, possibly a fully redesigned
  schema). Map from the captured fixture, not from the gem.
- **Do not rely on the IAG Developer Portal public API** (`api.ba.com/rest-v1/...`) for
  award availability. That API returns scheduled-flight data (schedules, prices for cash
  fares) and requires an approved developer account. It does not expose award seat counts
  or Avios redemption prices.

---

## Sources consulted

- `docs/probes/v1b-ba-rewards-research.md` — 2015 endpoint contract (authoritative for
  booking-class buckets and DDMMYYYY date format; dead for hostname/auth).
- `docs/probes/v1c-aeroplan-endpoint-discovery.md` — Aeroplan/Akamai auth pattern;
  structural analogy for `x-api-key` + Bearer token flow.
- [trickster.dev — mitmproxy with iOS 17.1](https://www.trickster.dev/post/setting-up-mitmproxy-with-ios17.1/) —
  current iOS proxy + CA trust procedure.
- [appknox.com — iOS SSL pinning bypass guide 2025](https://www.appknox.com/blog/bypass-ssl-pinning-in-ios-app) —
  Frida Gadget no-jailbreak approach; Objection automation; BoringSSL caveat.
- [curl_cffi PyPI / GitHub](https://github.com/lexiforest/curl_cffi) — TLS fingerprint
  impersonation for Python HTTP clients against Akamai-fronted endpoints.
- [Akamai blog — Bots Tampering with TLS](https://www.akamai.com/blog/security/bots-tampering-with-tls-to-avoid-detection) —
  confirms JA3/JA4 fingerprinting scope at Akamai Bot Manager layer.
- [IAG Developer Portal](https://developer.iairgroup.com/british_airways/ApiInfo) —
  confirms `api.ba.com/rest-v1/` is scheduled-flight only; no award availability exposed.
