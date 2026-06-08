# v1.5 Stagehand Feasibility — Research (Pre-Probe)

**Date:** 2026-06-07
**Author:** research agent
**Status:** desk research, gates live-probe task #30
**Scope:** Can Browserbase Stagehand reliably reach AA and Delta award-search pages? Decide whether to spend live-session time before committing v1.5.

---

## 1. Stagehand's actual browser-layer approach

Stagehand v3 went **CDP-native** in late 2025, dropping Playwright and talking to Chrome directly via DevTools Protocol — marketed as perf (44% faster on shadow DOM/iframes), not stealth ([Browserbase/Stagehand](https://github.com/browserbase/stagehand), [APIScout 2026](https://apiscout.dev/guides/stagehand-vs-playwright-ai-browser-automation-2026)). The Stagehand SDK itself ships no fingerprint hardening, proxy management, or CDP-leak patching — all of that lives in the **Browserbase cloud session**.

Browserbase's documented stealth posture is the surprising part. Per their own [Agent Auth & Identity docs](https://docs.browserbase.com/features/stealth-mode), the strategy is *recognition, not evasion*: "Rather than trying to evade detection, Verified browsers are recognized as legitimate by the protection systems themselves." This is implemented via **Web Bot Auth**, a signed-HTTP-request scheme co-launched with Cloudflare in late 2025 ([Cloudflare blog](https://blog.cloudflare.com/signed-agents/), [Browserbase blog](https://www.browserbase.com/blog/cloudflare-browserbase-pioneering-identity)); Browserbase is in Cloudflare's first signed-agents cohort. The platform also offers basic CDP-artifact suppression, navigator.webdriver patching, Canvas/WebGL fingerprint randomization, and residential proxy routing at $8/GB ([pricing](https://www.browserbase.com/pricing)) — baseline only, with the partnership story being the headline.

**Implication for autopoints:** Stagehand's stealth quality on a given target depends almost entirely on whether that target's WAF participates in Web Bot Auth allowlisting. Cloudflare yes. Akamai no.

## 2. PerimeterX / HUMAN — state of automated detection in 2026

PerimeterX (rebranded HUMAN Security in 2024) scores every visitor across **five layers** simultaneously: IP reputation, TLS/JA3, browser fingerprint (Canvas/WebGL/fonts/screen), session continuity, on-page behavior ([Scrapfly 2026 guide](https://scrapfly.io/blog/posts/how-to-bypass-perimeterx-human-anti-scraping), [ZenRows 2026](https://www.zenrows.com/blog/perimeterx-bypass)). Failure mode is the "Press & Hold" challenge.

Open-source bypass stacks (Camoufox + Browserforge, undetected-playwright, patchright) handle Cloudflare/DataDome reasonably but degrade on PerimeterX behavioral checks. Camoufox specifically fails closed against high-security PerimeterX configurations and has a year-long maintenance gap as of 2026 ([scrapewise 2026](https://scrapewise.ai/blogs/playwright-stealth-2026), [Camoufox stealth](https://camoufox.com/stealth/)). Community consensus: reliable bypass requires paid Web Unlocker APIs.

**However — and this matters — aa.com does NOT use PerimeterX.** April-2026 scraper reviews identify aa.com's actual stack as **Cloudflare Bot Management** ([Scraperly](https://scraperly.com/scrape/american-airlines)). The autopoints roadmap's PerimeterX assumption is outdated; the real adversary for AA is Cloudflare — which shifts the calculus in our favor, because Browserbase's signed-agents partnership directly targets Cloudflare.

## 3. Akamai Bot Manager — state in 2026

Akamai is harder than Cloudflare. The 2026 stack includes:

- **TLS fingerprinting (JA3/JA4)** as the single most effective gate — blocked before HTML loads ([Scrapfly Akamai 2026](https://scrapfly.io/blog/posts/how-to-bypass-akamai-anti-scraping), [VoidMob 2026](https://voidmob.com/blog/how-to-bypass-akamai-bot-detection-2026)).
- A ~50KB obfuscated `sensor.js`/`bmak` payload collecting 100+ passive signals (mouse, keyboard timing, scroll, touch, GPU, audio, WebRTC), POSTed as encrypted `sensor_data` to `/_sec/cp_challenge/verify`.
- **Per-customer-tuned scoring** across the session, not per-request — replayed sessions and inconsistent behavioral patterns fail.

Akamai sites block Camoufox where stock Firefox + raw Playwright loads cleanly ([Camoufox #555](https://github.com/daijro/camoufox/issues/555)) — Akamai already classifies known stealth-fork fingerprints. Akamai is **not** in Web Bot Auth, so Browserbase's partnership buys nothing here. Working approaches in 2026 are antidetect browsers (AdsPower, GoLogin) with human-pattern scripting, or paid Web Unlockers — Scrapfly advertises 97% against Akamai at per-request pricing ([Scrapfly Bypass Akamai](https://scrapfly.io/bypass/akamai)).

## 4. AA.com specifics

- **Anti-bot:** Cloudflare Bot Management (JS challenges, JA3/JA4, behavioral). Difficulty rated 2/5 "Easy" by Scraperly's 2026 test ([Scraperly](https://scraperly.com/scrape/american-airlines)).
- **Award search login:** No. Award flight availability can be browsed without an AAdvantage login (confirmed via [AAdvantage program FAQ](https://www.aa.com/web/i18n/aadvantage-program/answers-support/aadvantage-support.html) and 2026 award-search community reports). Logged-in only changes miles balance display.
- **MFA:** AA is mid-rollout of mandatory MFA for AAdvantage account login (started June 2025, weekly cohort expansion per [View from the Wing](https://viewfromthewing.com/american-airlines-rolling-out-required-multifactor-authentication-to-access-aadvantage-accounts/)). Email or SMS code, 15-min expiry. Triggers on new device — would break headless on every fresh session unless we persist storage state and complete one human MFA. Not blocking for logged-out award search.
- **Rendering:** Search result page is largely static HTML per Scraperly's testing, "search results and booking pages on aa.com don't require browser automation." This is good — even if Stagehand fails, plain `curl_cffi` + JA3-resistant requests likely work.
- **Living scrapers in 2026:** `tszumowski/aa_flight_search_tool` (Selenium, unmaintained), `luispic2021/aa_miles_monitor`, Apify's [Flight Award Scraper](https://apify.com/igolaizola/flight-award-scraper), and seats.aero ([seats.aero/american](https://seats.aero/american)) all still surface AA inventory.

## 5. Delta.com specifics

- **Anti-bot:** Akamai Bot Manager (industry-standard for Delta as a long-time Akamai customer; community consensus across [Scrapfly](https://scrapfly.io/blog/posts/how-to-bypass-akamai-anti-scraping), [scrapewise](https://scrapewise.ai/blogs/playwright-stealth-2026)).
- **Award search login:** Partially. Cash + miles toggle on delta.com flight search works without login for browsing, but to see *actual* SkyMiles award pricing reliably requires SkyMiles login. Confirmed via 2026 community reports and the explicit `mfa=true` parameter on [delta.com/skymiles/login](https://www.delta.com/skymiles/login?mfa=true).
- **MFA:** Yes, on SkyMiles login. Same problem as AA — new device triggers email/SMS code.
- **Rendering:** Delta's flight search is heavily client-side rendered with XHR fetches; not amenable to plain HTTP scraping.
- **Living scrapers in 2026:** AwardWiz lists Delta as "**temp broken**" and the repo was **archived September 11, 2024** ([github.com/lg/awardwiz](https://github.com/lg/awardwiz)). AwardHacker shut down March 2026 ([The Miles Market](https://www.themilesmarket.com/post/post-awardhacker-shut-down-alternatives)). Seats.aero still surfaces Delta inventory ([seats.aero/delta](https://seats.aero/delta)) but is in active litigation with Air Canada and historically Delta has issued cease-and-desist to AwardWallet/TripIt for SkyMiles API access ([Skift 2012](https://skift.com/2012/09/17/awardwallet-to-delta-skymiles-we-have-a-secure-solution-if-anyone-is-listening/)). **Delta is the canonical hard-mode airline.**

## 6. Recommendation — probe probability and cost

| Target | Realistic probe success | Confidence |
|---|---|---|
| aa.com logged-out award search | **70-85%** | High — Cloudflare + signed agents + static HTML is the easy path |
| aa.com logged-in (post-MFA, persisted state) | **50-65%** | Medium — MFA bootstrap is manual, Cloudflare may flag long-lived headless sessions |
| delta.com (logged-in award search) | **15-30%** | Low — Akamai + client-side render + MFA + Delta's hostile-to-scrapers history |

**Probe cost estimate:**
- Engineering: 6–10 person-hours per target to wire Stagehand + Browserbase + (for Delta) residential proxy + persisted storage state + MFA bootstrap flow.
- Browserbase session time: Hobby ($39/mo, 200 hr) covers iteration; expect ~5–15 GB residential proxy at $8/GB = $40–$120 burn over a serious probe week.
- Total: ~$60–$150 cash + 1–2 engineer-days for a defensible go/no-go signal across all three scenarios.

## 7. Strategy recommendation

**Run the probe — but only for AA, and re-scope first.** The PerimeterX assumption in v1.5 is wrong for AA (Cloudflare) and uninteresting for Delta (Akamai). Re-frame:

1. **AA (logged-out award search):** Try Stagehand on Browserbase with signed agents + stealth flag first. If that works, **also test `curl_cffi` + JA3-resistant headers** — Scraperly's evidence suggests Stagehand is overkill and HTTP-only is viable. Follow the `timrogers/ba_rewards` precedent: sniff aa.com's mobile/web XHR endpoints first.
2. **AA (logged-in):** Defer until logged-out works. The MFA-bootstrap + persist-storage-state pattern only earns its complexity if logged-in unlocks materially better data.
3. **Delta:** **Drop from v1.5 scope.** Akamai + MFA + active legal hostility + AwardWiz-archived-as-broken is too much risk. Revert STRATEGY.md to mark Delta as v2.0+, contingent on (a) Akamai joining Web Bot Auth, (b) a paid Web Unlocker justifying its cost, or (c) a SkyTeam partner-program source (Virgin Atlantic, Flying Blue) surfacing Delta inventory without touching delta.com.

If even AA logged-out fails after one engineer-day, ship v1.5 as "Direct providers: AA logged-out via HTTP only," cut Delta, route Delta value via SkyTeam partners.

---

**Sources** (all cited inline above): Browserbase docs and blogs, Cloudflare signed-agents blog, Scrapfly 2026 Akamai/PerimeterX guides, ZenRows 2026 PerimeterX guide, Scraperly 2026 American Airlines, View from the Wing AA MFA rollout, awardwiz GitHub (archived), seats.aero, Camoufox issue tracker, The Miles Market AwardHacker shutdown, APIScout Stagehand-vs-Playwright 2026.
