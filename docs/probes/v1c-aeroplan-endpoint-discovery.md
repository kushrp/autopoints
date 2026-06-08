# v1.c probe: Aeroplan endpoint rediscovery

**Status: working endpoint identified.** The Aeroplan award-search backend
has moved hosts (and the URL sub-path has changed) but the request/response
contract on the existing provider is still substantially correct. The blocker
for live calls is now Kasada bot management, not a dead DNS record.

Bottom line: repair the provider, do not retire it.

---

## 1. Verify the old endpoint is dead

`nslookup akamai-akwa-aeroplan.aircanada.com` returns **NXDOMAIN** from the
local resolver (Comcast 2600:4041:54da:4f00::1). `curl -I` against the same
URL fails with "Could not resolve host" (curl exit 6). The hostname is gone
from public DNS — not just firewalled. Confirmed 2026-06-07.

The current provider at `autopoints/providers/aeroplan.py:27-30` is therefore
correctly marked DEPRECATED.

---

## 2. The new endpoint

```
POST https://akamai-gw.dbaas.aircanada.com/loyalty/dapidynamicplus/1ASIUDALAC/v2/search/air-bounds
```

Two things changed vs. the value in `providers/aeroplan.py`:

| field           | old (NXDOMAIN)                                    | new (live)                               |
| --------------- | ------------------------------------------------- | ---------------------------------------- |
| host            | `akamai-akwa-aeroplan.aircanada.com`              | `akamai-gw.dbaas.aircanada.com`          |
| URL sub-path    | `/loyalty/dapidynamic/1ASIUDALAC/v2/search/...`   | `/loyalty/dapidynamicplus/1ASIUDALAC/v2/search/...` |
| `x-api-key`     | `1ASIUDALAC` (the same string also embedded in path) | `Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm` (rotated) |

Probe results from this machine (2026-06-07):

- `nslookup akamai-gw.dbaas.aircanada.com` -> CNAME chain to
  `akamai-gw.dbaas.aircanada.com.edgekey.net` -> `e10387.a.akamaiedge.net`
  (Akamai), resolves to 23.56.163.214.
- TLS cert SAN matches `*.dbaas.aircanada.com`, issued to "C=CA; ST=Quebec;
  O=Air Canada", valid Sep 2025 - Sep 2026.
- `POST /loyalty/dapidynamicplus/.../air-bounds` with the new `x-api-key`
  returns **HTTP 429** plus an `x-kpsdk-ct` header — i.e. Kasada bot
  management rejecting an unsolved-challenge request. (The same path on the
  legacy `dapidynamic` sub-path now returns a stream RST.)
- The fact that the path responds with a Kasada 429 (not 404 / not NXDOMAIN)
  confirms the route is live; the gate is the bot challenge, not the URL.

### Sub-path nuance

awardwiz's scraper waits on a glob `*/loyalty/dapidynamic/*/v2/search/air-bounds`
(see `lg/awardwiz` `awardwiz-scrapers/scrapers/aeroplan.ts` L13), which was
the path until at least Sept 2024 when the repo was archived. The fresh
RiskByPass demo (committed 2026-06-05, two days ago) hard-codes
`dapidynamic_plus_` instead. We observed `dapidynamic` returning stream-RST
and `dapidynamicplus` returning a clean Kasada 429 — so the migration to the
"plus" sub-path is recent and the RiskByPass value is the one to use.

---

## 3. Auth / handshake (this is the real work)

Two scrapers from the same code family (xmsley614/nt_tool, 237 stars;
Mad-LittleRookie/MilesSearch) show the same multi-step handshake that the
old aeroplan.py never implemented:

1. `POST https://cognito-identity.us-east-2.amazonaws.com/` with a hard-coded
   `IdentityId` (`us-east-2:7f9c31d7-d242-4f7e-afda-916b8c6c2b9c`) to get
   ephemeral AWS credentials.
2. `POST .../loyalty/dapidynamicplus/1ASIUDALAC/v2/reward/market-token`
   signed with SigV4 (`aws_host='api-gw.dbaas.aircanada.com'`, region
   `us-east-2`, service `execute-api`) -> returns `data.sessionToken`.
3. `POST .../v2/search/air-bounds` with headers `ama-client-ref` (UUID),
   `ama-session-token` (from step 2), and `x-api-key`. Body matches the
   shape we already have, with `searchPreferences.showSoldOut` etc.

The old provider sends only step 3 with the wrong `x-api-key`, no Cognito
creds, no SigV4 signature, no market-token. That is why simply patching the
URL is insufficient.

On top of the AWS layer, Air Canada wraps the whole thing in **Kasada**
(per the `x-kpsdk-ct` / `x-kpsdk-r` headers and the existence of
`kasada/aircanada.py` in RiskByPass's demo). Solving Kasada from a server
requires either a paid anti-bot API (RiskByPass, Kasada-bypass-as-a-service)
or a real browser via Browserbase/Arkalis-style infrastructure.

---

## 4. Sources

1. `nslookup` / `curl` from this host, 2026-06-07 (NXDOMAIN on the old host,
   429+Kasada on the new host).
2. `lg/awardwiz` (archived 2024-09-11) `awardwiz-scrapers/scrapers/aeroplan.ts`
   commit `master` — fetched via `gh api`. Uses the `dapidynamic` sub-path.
3. `xmsley614/nt_tool` `src/ac_searcher.py` (pushed 2023-07-10, 237 stars) —
   `akamai-gw.dbaas.aircanada.com`, x-api-key `Z5R8Rm...`, full AWS+market-token
   flow.
4. `hashmonkey404/award-ticket-search-tool` `ac_searcher.py` (2023-04) —
   identical hostname and api-key, independently committed.
5. `Mad-LittleRookie/MilesSearch` `src/ac_searcher.py` (2023-11) — same.
6. `RiskByPass/riskbypass_demo` `kasada/aircanada.py` (pushed 2026-06-05,
   213 stars) — uses `dapidynamicplus` sub-path; explicitly tags
   `protected_api_domain` and `kasada_js_domain` = `akamai-gw.dbaas.aircanada.com`.
7. seats.aero v. Air Canada lawsuit coverage (View From The Wing,
   AwardWallet, Aviation A2Z May 2026 update). The filings reference "API
   scraping" but do not name the endpoint URL; useful as confirmation that
   the program is actively defended, not as a source of the URL itself.
8. WebFetch of `https://www.aircanada.com/` timed out at 60s (Kasada
   interstitial), so the JS bundle was not retrieved via WebFetch. The
   endpoint shape was reconstructed from the GitHub corpus instead.

---

## 5. Recommendation: repair, do not retire

Minimal repair (lets `--live-aeroplan` succeed against an unprotected
network path, e.g. residential proxy + Browserbase):

1. In `autopoints/providers/aeroplan.py`, replace `_ENDPOINT` with
   `https://akamai-gw.dbaas.aircanada.com/loyalty/dapidynamicplus/1ASIUDALAC/v2/search/air-bounds`.
2. Replace `_DEFAULT_API_KEY` (`1ASIUDALAC`) with
   `Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm`. Note: the `1ASIUDALAC` in the
   URL path is a separate market/tenant code and stays.
3. Add the Cognito + SigV4 + market-token preflight before the air-bounds
   call. The AWS dependency is `aws-requests-auth` (or `botocore.auth.SigV4`
   directly to avoid the new dep).
4. Plumb Kasada handling through `_browserbase.py` — run the search through
   a real browser session and intercept the `air-bounds` response JSON, the
   way awardwiz did. The DIY signed-request path will fail Kasada in seconds.

Step 4 is the only one that gates real availability. Steps 1-3 are
mechanical and ~30 minutes of work. Keeping the provider opt-in behind
`--live-aeroplan` (current default off) is still correct; the chart-floor
AC provider remains the safety net.

Do not retire `--live-aeroplan`. The endpoint exists, is documented in
public scrapers updated within the last 72 hours, and the v0 architecture
already isolates this risk.
