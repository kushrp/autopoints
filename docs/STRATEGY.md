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
| [lg/awardwiz](https://github.com/lg/awardwiz) | **Archived Sep 2024.** Lost the anti-bot arms race — specifically, lost the *anti-fingerprinting* fight (Akamai detecting headless Chrome environment). Notably had authenticated sessions; that part of the design worked. |
| [flightplan-tool/flightplan](https://github.com/flightplan-tool/flightplan) | Stagnant. Node.js + Puppeteer. Covered AC, AS, BA, CX, KE, NH, SQ. |
| [timrogers/ba_rewards](https://github.com/timrogers/ba_rewards) | **Dead — and the maintainer agrees.** Last commit 2015-04-08, endpoint host NXDOMAIN, maintainer commented 2025-10-04 he'll archive the repo. Still useful as a **spec artifact** for booking-class buckets (X/P/U/Z), date format (DDMMYYYY), and response keys — see `docs/probes/v1b-ba-rewards-research.md`. |

The pattern most readings of these projects miss: **the projects that survived had real account auth; the ones that died lost to anti-bot fingerprinting, not to the auth problem.** This was buried by the framing "API-shaped reverse-engineering survives" — the *truer* lesson is that **authenticated sessions backed by real accounts route around 80% of the anti-bot war**, because you're inside the auth boundary the airline already permits.

## What every commercial tool fails to do

These are all surprisingly absent, even at $12/mo:

1. **Alert on what's new, not what's still cached.** Existing tools fire alerts every time a stale seat shows up. We compute a signature per (date, cabin, program, points) and tell you only when something genuinely new appears.
2. **CPP-threshold alerts.** Commercial tools alert on availability. We alert on *value* — "ping me only if CPP > 2.0¢."
3. **Discord as primary surface.** Everyone else builds a web/mobile app you have to remember to open. We treat the search as a slash command in a chat you're already in.
4. **CLI + cron friendly, MCP-pluggable.** `--json` flag, metro-code expansion (`NYC`, `LON`, `BAY`), `compare` subcommand for matrix searches, stable schema documented as MCP-consumable. No commercial tool exposes any of this — they're GUI-only. The same CLI surface is the MCP tool surface; agent callers and humans use identical contracts. See `Adjacent projects` below.
5. **Hackable.** MIT Python, one file per provider, zero abstractions per the YAGNI rule.
6. **Transfer-bonus math out of the box.** Effective CPP automatically applies the active Amex → Virgin 30% bonus. We don't make you do the arithmetic.
7. **Account-aware ranking.** Once authenticated sessions ship (see `Our actual strategy` below), search results filter against actual balances — "what you can book today" not "what theoretically exists at this price." Commercial tools can't do this because they don't have your accounts.

## What every commercial tool actually does better

Be honest:

- **Data velocity.** seats.aero refreshes premium-cabin availability in seconds because Ian Carroll spent his life as a security engineer and runs serious infra. We can't match this and won't try.
- **Coverage breadth.** seats.aero covers 25 programs; we cover the 4-5 programs you actually hold. **This isn't a gap we close; it's a different product.** A power-user tool serves the user's actual portfolio; a commercial tool serves the long tail. Earlier drafts of this doc framed coverage breadth as "the gap we have to close" — that framing was wrong and has been struck.
- **Booking flow.** Commercial tools link directly to the airline's booking page with the right state. Even with authenticated sessions we will *not* automate the booking step — the auth surface is for search, balance, and availability only, never for placing reservations.
- **Mobile UI.** pointsyeah ships a native app. We have a web UI you can save as a PWA + a Discord surface, which is good enough for personal use. Mobile isn't a north star.

## Adjacent projects

`points-deals` (private repo at `~/points-deals`) was a parallel start at the same problem with an MCP-first framing. It scaffolded schemas, a transfer-ratios engine, a DuckDB cache, macOS Keychain credential helpers, a FastMCP server skeleton, and a per-program `BaseScraper` interface — but no working scrapers shipped.

**Decision (2026-06-08): autopoints absorbs the useful parts of points-deals; points-deals is deprecated as a standalone project.** The two were targeting the same user with the same backend pattern and the same program list (including Delta, which autopoints had dropped). Running both is duplicate maintenance.

What gets pulled across into autopoints (follow-up port, not done yet):

- **`data/transfers.json`** — explicit bank → program transfer-ratio table with `min_increment` and per-edge notes. Cleaner than the current `valuations()` shape for transfer math.
- **`auth.py` keyring helper** — the right shape for credential storage; will get extended to wrap 1Password CLI (see authenticated-session direction below) rather than raw keyring.
- **`FastMCP` server skeleton** — direct port. autopoints's `--json` schema already mirrors `SearchOutcome`; wrapping it as MCP tools is a thin layer.
- **`BaseScraper` interface** with `requires_login: bool` and `fetch_balance()` — exactly the shape the authenticated-session direction needs.

What does not get pulled: `points-deals`'s `Program` enum (autopoints uses richer per-provider classes), the DuckDB cache (SQLite is sufficient at single-user scale), the standalone CLI (autopoints already has a better one).

## Our actual strategy

**Be the power-user tool, not the commercial one.** Specifically:

1. **Authenticated-session sourcing replaces anonymous endpoint reverse-engineering as the primary architecture.** The previous "hybrid: static charts + reverse-engineered live (unauth endpoints)" framing was the load-bearing assumption that just broke. Air Canada's unauthenticated IAM policy denies our auto-minted anonymous Cognito identity at the market-token resource, so the v1.c-2 "Browserbase + SigV4 from our side" plan is invalidated — see strategic revisions log. The architecture under design (brainstorm pending) is: log into each airline once via Browserbase, capture the session envelope (cookies, JWT, account-bound tokens), persist it (encrypted via 1Password CLI), and reuse it for subsequent searches. Re-login when expired. This is the same pattern AwardWiz used; AwardWiz died of fingerprint detection, not auth-flow attrition, and Browserbase's stealth handles the fingerprint that killed them. This shift unlocks Delta (TOTP via `op item get --otp` solves the MFA wall that justified dropping it) and should work for AA/BA/JetBlue with the same per-program login adapter pattern. Trade-off: the legal/ToS posture moves from "anonymous public endpoints" to "automated access to your own account" — see `What we'll never do` and the reverse-engineering disclaimer below for the boundary.
2. **Static charts stay as a fallback when live fails.** When a session is stale, a login flow regresses, or a provider is temporarily down, fall back to chart-floor estimates. Chart-floor is honest about being a floor; live is honest about being live. Never let a chart-floor estimate masquerade as live.
3. **Stale-availability re-verify lands alongside the first live provider, not after several.** Before any watchlist alert fires, re-hit the source for that specific (date, cabin, program). If it disappeared, suppress. Closes the pointsyeah complaint about phantom seats. Earlier drafts of this doc sequenced re-verification *after* multiple live providers shipped, which would have meant phantom alerts in the interim — corrected.
4. **Virgin Atlantic stays uncontested.** The community ran `vseats.io` for years as a human-driven daily scrape. A small program with low churn — sweet spot for a hobbyist. Authenticated-session sourcing is easier for VS than most because it's a single domain with stable login UI.
5. **Coverage is your portfolio, not seats.aero's catalog.** Cover the programs the user holds (Alaska, AA, JetBlue) + high-value transfer partners (Aeroplan, Virgin Atlantic) over time. **Authenticated sessions un-drop Delta** — the previous "drop Delta because MFA + Akamai + legal" reasoning was correct under the anonymous-endpoint architecture, but flips under authenticated sessions (TOTP via 1Password handles MFA; logged-in session sidesteps anonymous-tier Akamai checks; ToS exposure goes from "scraping" to "automating your own account" which is gray-zone but defensible at personal scale). Delta returns to scope under v2.e per the build order. **United stays out** (no direct membership; partner pricing via Aeroplan covers most United routes). *Updated 2026-06-08 — pre-pivot Delta-drop reasoning was sound for that architecture and is no longer load-bearing.*

   **Revert path:** If 1Password CLI or Browserbase become unavailable or unaffordable, every authenticated-session provider degrades cleanly to chart-floor estimates. The watchlist and CPP-ranking surface continues to work on the chart-floor fallback; only "live availability" goes dark per provider. This is the same revert posture v1 had — broader because every provider now shares one dependency.

## The build order

| # | Slice | Effort | Why now |
|---|---|---|---|
| 1 | NAS deployment | 1d | The product can't be useful if it's not always-on. ✅ done |
| 2 | Onboarding wizard | 1–2d | Setup friction is what kills hobbyist projects. ✅ done |
| 3 | **v0 foundational sprint** (`docs/brainstorms/2026-06-07-points-redemption-sprint-requirements.md`) | 1d sequential | Google Flights cash provider (replaces dying Amadeus) + schema migration + Alaska skeleton + `--arrive-before` filter. ✅ done — PR #3. |
| 3.5 | **v0.1 — post-review residuals** | 0.5d | 5 deferred `ce-code-review` findings. ✅ done — PR #4. |
| 4 | **v1.b — MCP-pluggable CLI surface** (just shipped) | 1d | `--json`, metro codes (NYC/LON/etc.), `compare` subcommand, cash auto-retry, default-on Aeroplan when Browserbase creds present. ✅ done — PR #9. The CLI is now the engine surface that MCP wraps. |
| 5 | **v1.c — Aeroplan endpoint repair** ❌ **invalidated 2026-06-08** | (would have been ~2d) | v1.c-1 shipped (handshake skeleton, PR #6); v1.c-2 shipped a Browserbase Kasada bypass (PR #9), but live testing revealed (a) the in-page `window.fetch` to `akamai-gw.dbaas.aircanada.com` is blocked by Dynatrace RUM + Kasada + Angular Zone.js before leaving the page, and (b) the auto-minted *anonymous* Cognito identity is 403-denied at the market-token resource by AC's IAM policy. Both failures point at the same architectural fix: authenticated sessions. v1.c is retired in favor of v2.a. The shipped v1.c-1/v1.c-2 code stays in the tree as scaffolding for v2.a's login-flow integration. |
| 6 | **v2.a — Authenticated-session foundation** ⬜ **next, design pending** | TBD — brainstorm first | Build the architecture under design: `SessionManager` + `op` (1Password CLI) wrapper + per-program login adapter pattern + Browserbase login driver + cached `storageState` encrypted via 1Password secure-note. First use case is Aeroplan, which forced the pivot. Brainstorm scoped before estimate is honest. |
| 7 | **v2.b — Live-endpoint canaries** ⬜ | 1d | Nightly synthetic search per live provider; alert on failure. Catches endpoint rotation, session expiry, anti-bot escalation before the user hits silent failures. Replaces the previous (quarterly refresh) framing which was the wrong model for the actual failure modes. |
| 8 | **v2.c — AA direct via authenticated session** ⬜ | 2–3d | Re-scoped from "v1.5 AA logged-out Cloudflare probe." Authenticated-session pattern means the Cloudflare-vs-PerimeterX distinction matters less — we're inside the auth boundary, not testing it. AA is the second use case and validates the per-program adapter abstraction. |
| 9 | **v2.d — BA Avios via authenticated session** ⬜ | 2–3d | Was v1.b "iOS-app mitmproxy capture, 2–4d." Authenticated-session pattern means we don't need the iOS capture spike — the web Avios login surface is enough. `ba_rewards` still useful as a spec artifact for booking-class buckets / date format / response keys, but the architecture is different. |
| 10 | **v2.e — Delta via authenticated session + 1Password TOTP** ⬜ | 2–3d | Un-drops Delta. The MFA wall that justified dropping it under the anonymous-endpoint architecture is solved by `op item get delta --otp`. |
| 11 | **v2.f — JetBlue via authenticated session** ⬜ | 1–2d | Falls out of the v2.a–c pattern. |
| 12 | **v2.g — Virgin Atlantic live** ⬜ | 2–3d | Uncontested. Stable login UI. Also the SkyTeam-partner sanity check on Delta value (assert empirically that VS surfaces useful Delta-metal inventory). |
| 13 | **v2.h — MCP server wrapper** ⬜ | 1d | Wrap the existing `--json` CLI surface as FastMCP tools (`search_award`, `list_programs`, `get_transfer_paths`, `get_balances`). Absorbs the `points-deals` server skeleton. Once shipped, retire `points-deals`. |
| 14 | **v2.i — Stale-availability re-verifier** ⬜ | 2d | Before any watchlist alert fires, re-hit the source. Moved up from the original "after multiple live providers" sequencing — needs to ship before watchlists go autonomous. |
| 15 | Quarterly chart/valuation refresh script + calendar | 0.5d setup + ~1h/quarter | Different from live-endpoint canaries — this is for static-chart drift, transfer bonuses, valuation tweaks. Script + calendar reminder. |

**Build-order sequencing rationale:** v2.a is the unblocker for everything below it; sequencing AA/BA/Delta/JetBlue/VS after v2.a is non-negotiable because they all reuse the same authenticated-session foundation. Within v2.c–v2.g, ordering is by probe-success expectation × user value: AA first (you hold it, login UI is stable), then BA (you hold it, Akamai but logged-in sidesteps), then Delta (un-drop, validates the MFA flow), then JetBlue (small but cheap given the foundation), then VS (transfer-partner depth). v2.h (MCP) can technically ship anytime after v1.b because the CLI surface is already there; it's listed at #13 because it's most useful with multiple live providers behind it.

Anything not on this list is deferred indefinitely.

## What we'll never do

- Scrape seats.aero / pointsyeah / point.me / any commercial competitor. Their ToS forbids it and there's nothing to gain.
- **Run a multi-tenant or public-facing instance.** Single-user, single-machine (or single-NAS), single-Discord-channel. The MCP server is fine over stdio for your own Claude Code / Codex sessions; not fine exposed over the network. The "personal use posture" line is held at the *user* boundary, not the *code* boundary — public source is OK; public deployment is not.
- Resell or distribute the tool at scale. The Air Canada lawsuit reset the cost/benefit; personal-use posture only.
- Accept paid API integrations that change our cost model. The whole point is ~$0/mo recurring (1Password is already paid).
- Build a hotel-redemption side. Different domain, different APIs, much less margin per redemption.
- **Place reservations programmatically.** Authenticated sessions are scoped to search, availability, and balance read-only. Booking is always a hand-off to the airline's website. This is the line that keeps the legal posture defensible — "automated read access to my own account data" is much weaker exposure than "automated transactions on my own account."
- **Pay for anti-bot bypass services** (RiskByPass, Scrapfly Web Unlocker, Kasada-bypass-as-a-service). Changes the cost model and the legal posture. Browserbase (already paid) is the only allowed anti-bot dependency, scoped to login-flow execution and (when a session is stale or absent) the in-browser request driver. If Browserbase plan caps are exceeded, the response is to drop a provider, not to add a second paid bypass service.
- **Scrape delta.com directly via anonymous endpoint reverse-engineering.** Authenticated-session sourcing is the allowed path — see strategy bullet 5. The 2026-06-08 "drop Delta" decision is reverted; the original blockers (mandatory MFA, Akamai, legal posture) are addressed by 1Password TOTP + logged-in session + read-only scope.

## Cost expectations

| Item | Cost |
|---|---|
| NAS hardware (already owned) | $0 |
| Browserbase subscription (user-held) | already paid |
| 1Password subscription (user-held, used for credential management) | already paid |
| GHCR public image hosting | $0 |
| Domain / public hosting | $0 (LAN + Discord only) |
| Optional residential proxy if IP-banned | ~$10/mo, postpone |
| **Total marginal recurring** | **$0/mo** |

Browserbase is no longer "the ceiling" in the anti-bot sense — it's a per-provider dependency for login execution and (sometimes) for live in-browser request driving. If usage scales above the current plan's quota, the answer is to drop a provider, not to upgrade. Compare to commercial alternatives at $99–$200/year; the savings are real and recurring; the trade-off is you fix things when they break and you accept the ToS exposure of automating access to your own accounts.

## The reverse-engineering disclaimer

Earlier drafts of this section anchored on a narrower claim: "we hit the same public award-search endpoints that seats.aero hits — JSON over HTTPS, no auth, no ToS clicks bypassed, same gray zone seats.aero walks." That framing matched the anonymous-endpoint architecture and is now historically accurate but no longer descriptive.

Under the authenticated-session architecture, the posture is more honest: we automate read-only access to *your own* loyalty accounts. Each airline's ToS likely prohibits "automated access" to your account in general; whether read-only access at personal-use scale is enforceable, or worth enforcing against a single user, is the gray zone we walk. The decision rule:

- **Read-only scope.** Search, availability check, balance fetch. Never booking, never transaction, never account modification. This keeps exposure asymmetrically low even if a program changes posture toward us.
- **One account per program, one machine.** No shared instances, no public MCP endpoints. The personal-use boundary is at the *user*, not the *code*.
- **Quarterly check the Air Canada lawsuit** ([seats.aero/lawsuit](https://seats.aero/lawsuit)). Any settlement or judgment changes the answer for everyone. Note: seats.aero's exposure was greater than ours (commercial, multi-tenant, anonymous-endpoint); a ruling against them is informative but not directly transferable.
- **If a program sends a cease-and-desist**, that program degrades to chart-floor immediately. Don't fight; fall back. Document the c&d in `docs/probes/` and treat that provider as dropped for the visible future.

For *distribution to many users*, the calculus changes meaningfully. Use this for yourself; don't run a public-facing instance; don't share your authenticated session blobs.

## Strategic revisions log

- **2026-06-08 — Architectural pivot to authenticated sessions.** v1.c-2 Browserbase + auto-mint SigV4 path tested live and failed twice: (a) the in-page `window.fetch` to `akamai-gw.dbaas.aircanada.com` from `page.evaluate()` is intercepted by Dynatrace RUM + Kasada challenge JS + Angular Zone.js and blocked before leaving the page; (b) the auto-minted anonymous Cognito identity is explicit-denied by AC's IAM policy at the market-token resource. Both failures point at the same fix: log in as a real user and reuse the authenticated session envelope. The architecture under design is brainstormed in a follow-up doc; v1.c is retired and reframed as v2.a. Delta returns to scope under v2.e (TOTP via 1Password solves the MFA wall that justified dropping it). The "live (have for AC)" claim in earlier strategy drafts is corrected — live AC was never reliably "had" under the anonymous architecture; it relied on a hardcoded IdentityId that AC has revoked at least once.
- **2026-06-08 — points-deals absorbed.** Decision to deprecate `~/points-deals` as a standalone project and migrate its useful parts (transfer-ratios JSON, auth helper shape, FastMCP server skeleton, BaseScraper interface) into autopoints. Single-source-of-truth for the user's award-search infrastructure.
- **2026-06-08 — Coverage-breadth framing struck.** Earlier drafts called seats.aero's 25-program coverage "the gap we have to close." That framing was commercial-mimicry; corrected to "coverage is your portfolio, not seats.aero's catalog." This unblocks honest scope decisions (JetBlue and VS are in because you hold them / want their transfer paths; United is out because Aeroplan covers it).
- **2026-06-08 — MCP first-class.** The CLI's `--json` schema is the MCP tool contract; `compare`, metro-codes, and the stable `SearchOutcome` shape are MCP-pluggable by design. MCP server wrapper lands as v2.h. Sister project points-deals is absorbed (see above).
- **2026-06-08 — BA Avios reframed (twice).** First pass (early 2026-06-08): `timrogers/ba_rewards` confirmed dead; v1.b sequenced as mitmproxy capture against current Avios iOS app, 2–4d. Second pass (late 2026-06-08): authenticated-session architecture replaces iOS capture — login via web Avios surface, reuse session, no mitmproxy needed. `ba_rewards` retained as a spec artifact for booking-class buckets / date format / response keys.
- **2026-06-08 — Aeroplan endpoint repaired then invalidated.** Old host `akamai-akwa-aeroplan.aircanada.com` is NXDOMAIN; new host `akamai-gw.dbaas.aircanada.com`, sub-path `dapidynamicplus`, rotated x-api-key `Z5R8Rm1sA37iC0gaS5kb69ltHwKBTYzUa89gQDwm`, stable IdentityPoolId `us-east-2:4a7f6b48-a8ab-499b-9e7f-31e79b54638e`. Provider repair shipped in PR #6 as v1.c-1; auto-mint Cognito + Browserbase Kasada bypass shipped in PR #9 as v1.c-2 — both invalidated by IAM denial + in-page fetch block. Endpoint and pool ID remain stable inputs to v2.a (the authenticated-session path uses the *same* endpoints; the difference is whose IAM role signs the request).
- **2026-06-08 — AA reclassified, Delta un-dropped.** Earlier-in-the-day update reclassified AA from PerimeterX to Cloudflare, dropped Delta indefinitely. Late-day pivot to authenticated sessions makes the bot-management classification less load-bearing (we're inside the auth boundary), and un-drops Delta (TOTP via 1Password handles MFA). Both reasonings were valid under their respective architectures; the architecture moved.
