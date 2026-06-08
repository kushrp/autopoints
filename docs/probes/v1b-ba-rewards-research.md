# v1.b probe: porting `timrogers/ba_rewards`

**Status: caveat emptor.** Upstream endpoint is dead, maintainer agrees, and there
is zero test coverage in upstream. Read §7 before §6 — v1.b's critical-path task is
rediscovering a working endpoint, not translating Ruby. The brief still catalogs the
2015 contract so a fresh mitmproxy capture has a reference shape.

Sources pinned to `master` HEAD `6750ebf` (2015-04-08) — repo has had no commits since.

---

## 1. Auth flow

**There is no auth.** `lib/ba_rewards.rb` L4-5 declares
`base_uri 'dev1-flightavail-avios.bitnamiapp.com:8080/flight-availability-ws'`
then issues a plain `HTTParty.get(...)` with only query-string params. No
`Authorization` header, no cookie jar, no API key, no device-ID handshake. The
`gemspec` lists `httparty` + `activesupport` only (no `oauth2`, `jwt`, `faraday-cookies`).

User supplies **nothing** — no BA Exec Club creds, no device ID. The endpoint was a
Bitnami-hosted dev server that fronted the iOS app's availability service and was
open to any caller who knew the path. No session-token plumbing to port — until
rediscovery (§7) proves otherwise.

---

## 2. Request shape

From `lib/ba_rewards.rb` L9-14:

- **Base URL**: `http://dev1-flightavail-avios.bitnamiapp.com:8080/flight-availability-ws`
  (port 8080, plain HTTP).
- **Path / method**: `GET /departure/cities/{from}/destination/{to}`.
- **Query params** (all required; no body):
  - `obDate` — outbound date, `DDMMYYYY` (commit `6750ebf` pinned this).
  - `cabinClass` — single capital letter `E` / `P` / `B` / `F`.
  - `sc` — booking-class bucket `X` / `P` / `U` / `Z` (L55-62).
- **Headers**: HTTParty defaults only — no `X-Api-Key`, no `X-Device-Id`, no signing.
- **Absent**: return date, passenger count (`number_of_seats` is client-side filter).

Critical mismatch with autopoints' model: the endpoint is not "flights between O/D
on date X" — it's "cheapest Avios for O→D, plus which dates in next 12 months have
≥1 seat in this cabin." Affects §6 adapter design.

---

## 3. Response shape

Inferred from how `ba_rewards.rb` / `result.rb` consume it — no fixture is checked
in. Top-level JSON keys:

- `cityName`, `countryName`, `regionName` — destination metadata strings (L20-22).
- `prices.rfs` — Reward Flight Saver flag, numeric; `> 0` ⇒ RFS-eligible
  (`result.rb` L5).
- `prices.prices.A` — the *return* Avios price (L27). Only the `"A"` key is
  consumed; other keys may exist for one-way / per-cabin variants.
- `out[]` — per-date availability rows (L43-47): `d` (date string) and
  `bs` (seat count at the Avios price).

**No per-flight fields**: no carrier, flight number, times, fare basis, taxes,
or stops. The endpoint reports *availability per day* + one *route-level Avios
price*.

**Errors**: non-200 → `BARewardsException("The server responded with an error.")`
(L41); JSON parse failure → `BARewardsException("The response couldn't be
parsed...")` (L37). Real error-body shape is undocumented.

---

## 4. Awards-specific knowledge baked in

`ba_rewards` is mostly *un*opinionated about the BA award world:

- **Peak vs off-peak**: not handled. One `prices.A` per route; peak/off-peak
  variance only shows up indirectly as per-date `bs` deltas in `out`.
- **Reward Flight Saver**: the only redemption concept captured. `prices.rfs > 0`
  ⇒ RFS-eligible route with a capped cash co-pay. Cash component itself is **not**
  returned.
- **Saver vs standard tiers**: not surfaced — gem reads only `prices.A`.
- **Partner-award coverage**: not addressed. Endpoint is BA-metal only. Iberia /
  Aer Lingus / Qatar / Cathay partner Avios — the high-CPP redemptions — are
  out of scope.
- **Cabin → booking class** (L55-62): `{economy: "X", premium: "P", business: "U",
  first: "Z"}`. Keep verbatim; these are Avios distribution buckets.

---

## 5. Code architecture

- **Language**: Ruby 1.9+. ~80 LOC total across 3 files.
- **Dependencies**: `httparty`, `activesupport` runtime; `rspec ~> 2.14`, `rake` dev.
  `activesupport` used only for `Date.parse`.
- **Modules**:
  - `lib/ba_rewards.rb` — `BARewards` module, `availability` class method,
    `parse_availability_dates`, `cabin_class_to_sc_mapping`, `BARewardsException`.
  - `lib/ba_rewards/result.rb` — value object with `city`, `country`, `region`,
    `reward_flight_saver`, `availability_dates`, `avios_price`, `raw_response`.
  - `lib/ba_rewards/version.rb` — version constant.
- **Tests**: `spec/` referenced by `gemspec` but absent from the tree. **Zero
  test coverage shipped.**
- **License**: MIT.
- **Maintenance**: dead. Last commit 2015-04-08. Maintainer comment on
  `issues/2#issuecomment-3368081920` (2025-10-04): *"Sadly this has been dead
  for many years! I'll archive this repo."* 8 stars, 3 forks.

---

## 6. Porting checklist for `autopoints/providers/british_airways.py`

Target shape stays valid even if the endpoint must be rediscovered — autopoints-side
contract is independent of the wire URL.

- **Class**: `BritishAirwaysProvider(AwardProvider)` in
  `autopoints/providers/british_airways.py`. `name = "british_airways"`,
  `program_code = "BA"`.
- **Pattern**: mirror `autopoints/providers/aeroplan.py` — module-level
  `_ENDPOINT`, `_CABIN_MAP`, constructor-injected `httpx.AsyncClient` with
  browser-shaped headers, module-private `_parse_*` for defensive JSON walking.
- **Settings**: **no new env vars**. Reserve `ba_endpoint: str = ""` in
  `autopoints/config.py` so a rediscovered URL can be supplied per-deploy.
- **Cabin → query**: `{economy: ("E","X"), premium_economy: ("P","P"),
  business: ("B","U"), first: ("F","Z")}`.
- **Date format**: `depart_date.strftime("%d%m%Y")` for `obDate`.
- **Adapter → `AwardOffer`**: emit one `AwardOffer` per `out[i]` row where
  `out[i].d == depart_date`, with:
  - `provider = "BA"`, `operating_carrier = "BA"`,
  - `points = response["prices"]["prices"]["A"]` (return ticket — halve for
    one-way + warn, or gate round-trip semantics behind a v1.b flag),
  - `taxes_cents = 0` for non-RFS; for `rfs > 0`, fill from the static RFS
    chart in `autopoints/programs/award_charts/`,
  - `fare_class = sc letter`, `stops = 0` (endpoint reports non-stops; confirm
    in rediscovery),
  - **`departure_time / arrival_time / arrival_date / origin_tz / dest_tz =
    None`**. The endpoint does not return time-of-day; `arrive_before_local`
    filter passes through per `autopoints/search/models.py` L26-28. Document
    that BA results are not time-filterable.
- **Errors** (`autopoints.providers.base.ProviderError`):
  - `httpx.HTTPError` → `ProviderError("BA request failed: …")`
  - non-200 → `ProviderError("BA returned {status}: …")` with a targeted
    401/403/404 hint pointing at this doc ("endpoint likely retired").
  - JSON / `KeyError` on `prices.prices.A` → `ProviderError("BA parse failed: …")`.
- **Wiring**: `BritishAirwaysProvider` added in `autopoints/search/build.py`
  behind `BuildOptions.use_live_ba`, default off, mirroring Alaska.
- **Tests**:
  - `tests/test_british_airways.py` (respx-mocked):
    - happy path: `{"cityName":"San Francisco","prices":{"rfs":0,"prices":
      {"A":50000}},"out":[{"d":"2026-07-15","bs":2}]}` ⇒ one offer, points=50000,
      no `departure_time`.
    - empty `out` ⇒ `[]`.
    - 404 ⇒ `ProviderError` with rediscovery hint.
    - malformed JSON ⇒ `ProviderError("parse")`.
  - `tests/e2e/test_british_airways.py` with `@pytest.mark.e2e`: skipped unless
    `BA_LIVE_ENDPOINT` is set; LHR→JFK 6mo out, asserts ≥1 offer.

---

## 7. Risks / unknowns

- **Endpoint is dead.** `curl --max-time 8` against the Bitnami host returns
  HTTP `000` (NXDOMAIN). Maintainer confirmed in
  [issues/2#issuecomment-3368081920](https://github.com/timrogers/ba_rewards/issues/2#issuecomment-3368081920)
  (2025-10-04): *"Sadly this has been dead for many years! I'll archive this
  repo."* The v1.b critical path is **rediscover whether the BA Avios iOS app
  still exposes a clean JSON backend, and at what URL** — install the iOS app,
  mitmproxy/Charles capture, confirm shape, *then* port.
- **No upstream tests / no fixtures.** §3's response shape is inferred from how
  the Ruby reads the response, not from a real body. A captured fixture from the
  modern iOS app is needed before the unit tests in §6 are meaningful.
- **No per-flight data.** Even if the endpoint comes back, the gem yields
  `(avios_price, available_dates[])` — a calendar, not flight rows. The autopoints
  schema (`flight_numbers`, `departure_time`, `stops`) cannot be filled from
  this endpoint alone. The iOS app likely calls a separate per-day-detail
  endpoint; rediscovery must capture both.
- **Partner-award gap.** Original endpoint was BA-metal only. Iberia / Aer Lingus
  / Qatar / Cathay partner Avios — the highest-CPP redemptions — were never in
  scope. If the replacement also lacks partner coverage, autopoints needs a
  second pathway (ba.com booking widget reverse-engineering) for the partner
  story to land.
- **Modern anti-bot.** 2015 code saw no rate-limits, MFA, or session expiry. The
  modern BA stack (`api.britishairways.com`, `loyalty.ba.com`) is wrapped by
  Akamai Bot Manager. Plan for cookie sessions, possible reCAPTCHA, per-IP
  rate-limits, and TLS-fingerprint blocks against `httpx` defaults — which would
  push toward `curl_cffi` or Browserbase, undercutting STRATEGY.md's "pure HTTP,
  no browser" framing.
- **STRATEGY.md framing needs updating.** `docs/STRATEGY.md` L52 calls this
  *"pure HTTP, no browser, no anti-bot war"* and *"single highest-leverage move
  available"*. That was true in 2014. v1.b should open with a half-day
  mitmproxy spike whose outcome gates the rest of the milestone — if the iOS
  app now talks to an Akamai-fronted endpoint with cert pinning, the leverage
  calculus changes and v1.b may need to pivot.

---

## TL;DR for the v1.b plan

`ba_rewards` is a **specification artifact, not a working scraper**. Authoritative
for: (a) booking-class buckets X/P/U/Z, (b) `DDMMYYYY` date format, (c) URL path
shape `/departure/cities/{O}/destination/{D}`, (d) response keys (`cityName`,
`prices.rfs`, `prices.prices.A`, `out[].d`, `out[].bs`). **Unknown** for: hostname,
HTTP vs HTTPS, auth, per-flight detail, partner coverage. Front-load v1.b with a
mitmproxy capture of the modern BA Avios iOS app — that's where the actual
high-leverage discovery lives.
