# Why autopoints exists, and where it can win

A short, opinionated read-out from a competitive look at points.yeah, seats.aero, point.me, AwardFares, AwardHacker, ExpertFlyer, and the open-source projects that have come and gone (AwardWiz, Flightplan, ba_rewards).

## The landscape

| Tool | Price | What they actually do |
|---|---|---|
| [seats.aero](https://seats.aero/) | $9.99/mo or $99/yr Pro | Scrapes 25 airline loyalty programs continuously, refreshing premium cabins second-by-second. **$1.5M ARR, solo founder, no VC.** Sued by Air Canada in Oct 2023; still operating. |
| [pointsyeah](https://www.pointsyeah.com/) | Free + $11.99/mo Premium | Live scrapes + 60-day cache. 20+ programs. Mobile-first. $1M seed, 2 founders. Users complain about phantom availability, 4-day search window, app crashes. |
| [point.me](https://www.point.me/) | $12/mo or $99/yr | VC-backed, polished UX. Reputation: "painfully slow", single-day searches only, no flex-date discovery. |
| [AwardFares](https://awardfares.com/) | $10–20/mo | 15+ programs, real-time, per-program seat counts. Smaller user base than the two above. |
| [ExpertFlyer](https://www.expertflyer.com/) | $7–20/mo | Specific-flight inventory alerts (not award discovery). |
| [AwardHacker](https://awardhacker.com/) | dead | Fixed-chart calculator. Dynamic pricing killed it. |
| [AwardWallet](https://awardwallet.com/) | $30/yr | Portfolio tracker, not a searcher. |

## What the open-source community tried

| Project | Outcome |
|---|---|
| [lg/awardwiz](https://github.com/lg/awardwiz) | **Archived Sep 2024.** Lost the anti-bot arms race. Read its custom evasion engine ("Arkalis") for ideas, don't fork. |
| [flightplan-tool/flightplan](https://github.com/flightplan-tool/flightplan) | Stagnant. Node.js + Puppeteer. Covered AC, AS, BA, CX, KE, NH, SQ. |
| [timrogers/ba_rewards](https://github.com/timrogers/ba_rewards) | **Dead — and the maintainer agrees.** Last commit 2015-04-08, endpoint host NXDOMAIN, maintainer commented 2025-10-04 he'll archive the repo. Still useful as a **spec artifact** for booking-class buckets (X/P/U/Z), date format (DDMMYYYY), and response keys — see `docs/probes/v1b-ba-rewards-research.md`. Modern BA stack is Akamai-fronted; a working scraper requires a fresh mitmproxy capture of the current Avios iOS app, not a port. |

The clear pattern: web-scraping projects die. API-shaped reverse-engineering survives.

## What every commercial tool fails to do

These are all surprisingly absent, even at $12/mo:

1. **Alert on what's new, not what's still cached.** Existing tools fire alerts every time a stale seat shows up. We compute a signature per (date, cabin, program, points) and tell you only when something genuinely new appears.
2. **CPP-threshold alerts.** Commercial tools alert on availability. We alert on *value* — "ping me only if CPP > 2.0¢."
3. **Discord as primary surface.** Everyone else builds a web/mobile app you have to remember to open. We treat the search as a slash command in a chat you're already in.
4. **CLI + cron friendly.** No commercial tool gives you a `--json` flag you can pipe into a bash script.
5. **Hackable.** MIT Python, one file per provider, zero abstractions per the YAGNI rule.
6. **Transfer-bonus math out of the box.** Effective CPP automatically applies the active Amex → Virgin 30% bonus. We don't make you do the arithmetic.

## What every commercial tool actually does better

Be honest:

- **Data velocity.** seats.aero refreshes premium-cabin availability in seconds because Ian Carroll spent his life as a security engineer and runs serious infra. We can't match this.
- **Coverage breadth.** seats.aero covers 25 programs; we cover 3 statically + 1 live. That's the gap we have to close.
- **Booking flow.** Commercial tools link directly to the airline's booking page with the right state. We don't have OAuth into your loyalty accounts (and aren't going to).
- **Mobile UI.** pointsyeah ships a native app. We have a web UI you can save as a PWA, which is good enough but not what a casual user expects.

## Our actual strategy

**Be the power-user tool, not the commercial one.** Specifically:

1. **Hybrid sourcing.** Static charts (have) + reverse-engineered live (have for AC, plan for BA) + chart-floor fallback when live fails. No paid feeds.
2. **BA via fresh iOS-app capture, not a 2015 port.** *Updated 2026-06-08 based on `docs/probes/v1b-ba-rewards-research.md`.* The original "port `timrogers/ba_rewards`" plan assumed a still-live, unauthenticated Bitnami endpoint. That endpoint is NXDOMAIN, the maintainer is archiving the repo, and the modern BA stack (`api.britishairways.com`, `loyalty.ba.com`) is Akamai-fronted with likely cert pinning, TLS fingerprinting, and session cookies. The recommended approach is still **mitmproxy/Charles capture of the current Avios Flight Finder iOS app** — but it is no longer drop-in low-effort, and "pure HTTP, no anti-bot war, single highest-leverage move" no longer applies. Treat `ba_rewards` as a *spec artifact* (booking-class buckets, date format, response keys) and budget v1.b for a half-day capture spike that gates the rest of the milestone. If the modern endpoint is Akamai-gated, expect a Browserbase or `curl_cffi` fallback similar to v1.c, and re-rank against AA-via-Cloudflare.
3. **Stale-availability re-verify.** Before any watchlist alert fires, re-hit the source for that specific (date, cabin, program). If it disappeared, suppress. Closes the pointsyeah complaint about phantom seats.
4. **Virgin Atlantic.** Uncontested. The community ran `vseats.io` for years as a human-driven daily scrape. A small program with low churn — sweet spot for a hobbyist.
5. **Direct-program coverage is on the roadmap, shipped incrementally with evidence at each step.** Cover the user's held programs (Alaska, AA, JetBlue) over time. **Alaska ships first in v0** — lightest backend, hand-rolled Playwright via Browserbase, partner sweet spots. **AA is now the lead direct candidate**: per `docs/probes/v15-stagehand-feasibility-research.md`, aa.com is actually **Cloudflare Bot Management** (not PerimeterX as previously briefed), rated 2/5 "Easy" by Scraperly, award search works **logged-out** (no MFA bootstrap blocking v1.5), and Browserbase's Web Bot Auth partnership with Cloudflare directly applies. Estimated probe success 70–85%. **Delta is dropped from scope.** Delta is Akamai + client-side render + mandatory MFA + Delta's historic cease-and-desist posture (AwardWiz archived it as "temp broken"); estimated probe success 15–30% at $60–$150 burn. Route Delta value via SkyTeam partners (Virgin Atlantic, Flying Blue) instead. JetBlue follows Alaska once the base class extraction is justified. **United stays out** (no direct membership; partner pricing via Aeroplan covers most United routes). **Hand-rolled Playwright remains the default**; Stagehand is a candidate, not a strategic commitment. *Updated 2026-06-08 — AA reclassified from PerimeterX to Cloudflare (much easier); Delta dropped indefinitely.*

   **Revert path:** If Browserbase becomes unavailable or unaffordable, AA direct reverts to "skip" per the original strategy. Alaska + JetBlue can fall back to direct Playwright with a residential proxy if needed. The roadmap addition is reversible.

## The build order

| # | Slice | Effort | Why now |
|---|---|---|---|
| 1 | NAS deployment | 1d | The product can't be useful if it's not always-on. ✅ done |
| 2 | Onboarding wizard | 1–2d | Setup friction is what kills hobbyist projects. ✅ done |
| 3 | **v0 foundational sprint** (this brief: `docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md`, revised after ce-doc-review) | 1d sequential | Google Flights cash provider (replaces dying Amadeus) + schema migration for arrival-time + Alaska direct provider + CLI arrival-time filter. Sunday flight booking decoupled via manual checks. |
| 3.5 | **v1.c — Aeroplan endpoint repair (IN PROGRESS)** | v1.c-1 mechanical, v1.c-2 = Browserbase work | Provider repair shipped in PR #6 (new host `akamai-gw.dbaas.aircanada.com`, new x-api-key `Z5R8Rm…`, Cognito + SigV4 + market-token handshake) — endpoint is live, gated by Kasada bot management. v1.c-2 routes the air-bounds call through Browserbase to clear Kasada. See `docs/probes/v1c-aeroplan-endpoint-discovery.md`. |
| 4 | **v1.b — BA Avios live via fresh iOS-app capture** | **2–4d** (was 1–2d) | Heavier than originally estimated: the 2015 `ba_rewards` endpoint is dead, so v1.b starts with a half-day mitmproxy spike against the current Avios Flight Finder iOS app, then a port. Modern BA stack is Akamai-fronted — budget Browserbase or `curl_cffi` fallback. See `docs/probes/v1b-ba-rewards-research.md`. |
| 4.5 | **v1.5 — AA direct (logged-out, Cloudflare)** | 1 engineer-day probe + 1–2d build if probe passes | Re-scoped from "AA + Delta gated on PerimeterX probe" to **AA-only, logged-out, Cloudflare**. Stagehand on Browserbase with signed agents first; also test `curl_cffi` + JA3-resistant headers per Scraperly evidence. Delta dropped indefinitely. See `docs/probes/v15-stagehand-feasibility-research.md`. |
| 5 | Stale-availability re-verifier | 2d | Distinguishes our alerts from pointsyeah's. |
| 6 | Virgin Atlantic live | 2–4d | Uncontested, fills the third major chart provider with live data. Also the SkyTeam-partner pathway for Delta value now that Delta-direct is dropped. |
| 7 | Quarterly refresh process | recurring | Valuations, transfer bonuses, chart drift. Calendar reminder + a single script. |

Anything not on this list is deferred indefinitely.

## What we'll never do

- Scrape seats.aero / pointsyeah / point.me / any commercial competitor. Their ToS forbids it and there's nothing to gain.
- Resell or distribute the tool publicly at scale. The Air Canada lawsuit reset the cost/benefit; personal-use posture only.
- Accept paid API integrations that change our cost model. The whole point is $0/month.
- Build a hotel-redemption side. Different domain, different APIs, much less margin per redemption.
- Build a booking flow. Always link out to the airline's site.
- **Scrape delta.com directly.** *Added 2026-06-08.* Akamai + client-side render + mandatory MFA + Delta's historic cease-and-desists make the cost/benefit indefensible. Route Delta value via SkyTeam partner programs (Virgin Atlantic Flying Club, Air France/KLM Flying Blue) instead. Revisit only if (a) Akamai joins Web Bot Auth, (b) a paid Web Unlocker becomes justifiable, or (c) a SkyTeam partner source surfaces Delta inventory cleanly.
- **Pay for anti-bot bypass services** (RiskByPass, Scrapfly Web Unlocker, Kasada-bypass-as-a-service). Changes the cost model and the legal posture. Browserbase (already paid) is the ceiling.

## Cost expectations

| Item | Cost |
|---|---|
| NAS hardware (already owned) | $0 |
| Amadeus Self-Service (decommissioned 2026-07-17) | $0 → N/A |
| Google Flights via Browserbase (replacement cash source) | included in Browserbase subscription |
| Browserbase subscription (user-held) | already paid |
| GHCR public image hosting | $0 |
| Domain / public hosting | $0 (LAN + Discord only) |
| Optional residential proxy if IP-banned | ~$10/mo, postpone |
| **Total recurring** | **$0/mo** |

Compare to commercial alternatives at $99–$200/year. The savings are real and recurring; the trade-off is you fix things when they break.

## The reverse-engineering disclaimer

This project hits the same public award-search endpoints that seats.aero hits — they're just JSON over HTTPS, no authentication tokens stolen, no ToS clicks bypassed. For personal use this is the same gray zone seats.aero walks; they got sued by Air Canada and are still operating, which is a useful data point. For *distribution to many users*, the calculus changes. Use this for yourself; don't run a public-facing instance.

The Air Canada lawsuit ([seats.aero/lawsuit](https://seats.aero/lawsuit)) is worth checking quarterly. Any judgment changes the answer for everyone in this space.

## Strategic revisions log

- **2026-06-08 — BA Avios reframed** (per `docs/probes/v1b-ba-rewards-research.md`). `timrogers/ba_rewards` confirmed dead: endpoint NXDOMAIN, last commit 2015-04-08, maintainer agreed to archive. The original "pure HTTP, no anti-bot war, single highest-leverage move" framing was true in 2014 but not today — modern BA stack is Akamai-fronted. v1.b is now a fresh mitmproxy-capture spike against the current Avios iOS app, not a port. Effort budget raised from 1–2d to 2–4d. `ba_rewards` retained as a spec artifact for booking-class buckets / date format / response keys.
- **2026-06-08 — Aeroplan endpoint repaired** (per `docs/probes/v1c-aeroplan-endpoint-discovery.md`). Old host `akamai-akwa-aeroplan.aircanada.com` is NXDOMAIN; new host `akamai-gw.dbaas.aircanada.com`, sub-path `dapidynamicplus`, rotated x-api-key `Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm`. Provider repair (Cognito + SigV4 + market-token handshake) shipped in PR #6 as v1.c-1. Endpoint is Kasada-fronted; v1.c-2 routes the call through Browserbase. `--live-aeroplan` retained, not retired.
- **2026-06-08 — AA reclassified, Delta dropped** (per `docs/probes/v15-stagehand-feasibility-research.md`). aa.com is **Cloudflare Bot Management**, not PerimeterX as originally briefed — rated 2/5 "Easy", award search works logged-out, and Browserbase's Web Bot Auth partnership applies directly. v1.5 probe success estimated 70–85%; AA is now the lead direct candidate. Delta is dropped indefinitely: Akamai + client-side render + mandatory MFA + active legal hostility + AwardWiz archived-as-broken put probe success at 15–30% with no clean path. Route Delta value via SkyTeam partners (Virgin Atlantic, Flying Blue).
