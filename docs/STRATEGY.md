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
| [timrogers/ba_rewards](https://github.com/timrogers/ba_rewards) | **Alive and elegant.** Hits BA's *undocumented iOS Avios Flight Finder API* instead of scraping the web. Worth porting to Python. |

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
2. **The iOS API trick.** BA exposes a clean, undocumented JSON API via its Avios Flight Finder iOS app. Port `timrogers/ba_rewards` to Python; ship as the second live provider. This is the single highest-leverage move available.
3. **Stale-availability re-verify.** Before any watchlist alert fires, re-hit the source for that specific (date, cabin, program). If it disappeared, suppress. Closes the pointsyeah complaint about phantom seats.
4. **Virgin Atlantic.** Uncontested. The community ran `vseats.io` for years as a human-driven daily scrape. A small program with low churn — sweet spot for a hobbyist.
5. **Direct-program coverage is on the roadmap, shipped incrementally with evidence at each step.** Cover the user's held programs (Alaska, AA, Delta, JetBlue) over time. **Alaska ships first in v0** — lightest backend, hand-rolled Playwright via Browserbase, partner sweet spots. **AA and Delta are candidates**, gated on a 30-min Stagehand probe against PerimeterX (AA) and Akamai (Delta). Until the probe succeeds and AA's logged-in/MFA flow is scoped, AA and Delta direct stay deferred. JetBlue follows Alaska once the base class extraction is justified. **United stays out** (no direct membership; partner pricing via Aeroplan covers most United routes). **Hand-rolled Playwright remains the default**; Stagehand is a candidate, not a strategic commitment. *Updated 2026-06-07 — original position to skip all dynamic-pricing direct programs revised after ce-doc-review surfaced both the schema-migration scope and the Stagehand unproven-against-PerimeterX risk.*

   **Revert path:** If Browserbase becomes unavailable or unaffordable, AA and Delta direct revert to "skip" per the original strategy. Alaska + JetBlue can fall back to direct Playwright with a residential proxy if needed. The roadmap addition is reversible.

## The build order

| # | Slice | Effort | Why now |
|---|---|---|---|
| 1 | NAS deployment | 1d | The product can't be useful if it's not always-on. ✅ done |
| 2 | Onboarding wizard | 1–2d | Setup friction is what kills hobbyist projects. ✅ done |
| 3 | **v0 foundational sprint** (this brief: `docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md`, revised after ce-doc-review) | 1d sequential | Google Flights cash provider (replaces dying Amadeus) + schema migration for arrival-time + Alaska direct provider + CLI arrival-time filter. Sunday flight booking decoupled via manual checks. |
| 4 | BA Avios live (iOS API port) | 1–2d | Biggest data-coverage win on the partner side, still highest-leverage. Schedule immediately after v0. |
| 4.5 | AA + Delta direct (gated on Stagehand probe) | 2–3d | Only if 30-min probe succeeds + AA logged-in/MFA flow scoped. Otherwise stays deferred. |
| 5 | Stale-availability re-verifier | 2d | Distinguishes our alerts from pointsyeah's. |
| 6 | Virgin Atlantic live | 2–4d | Uncontested, fills the third major chart provider with live data. |
| 7 | Quarterly refresh process | recurring | Valuations, transfer bonuses, chart drift. Calendar reminder + a single script. |

Anything not on this list is deferred indefinitely.

## What we'll never do

- Scrape seats.aero / pointsyeah / point.me / any commercial competitor. Their ToS forbids it and there's nothing to gain.
- Resell or distribute the tool publicly at scale. The Air Canada lawsuit reset the cost/benefit; personal-use posture only.
- Accept paid API integrations that change our cost model. The whole point is $0/month.
- Build a hotel-redemption side. Different domain, different APIs, much less margin per redemption.
- Build a booking flow. Always link out to the airline's site.

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
