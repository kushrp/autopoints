# Research findings — competitive landscape

Raw output from three parallel research passes covering the commercial tools, technical architecture, and open-source ecosystem. Source URLs cited inline. Speculation flagged.

Synthesized version with build recommendations lives in [STRATEGY.md](STRATEGY.md).

---

## PointsYeah

**Product.** Freemium award-flight + hotel search at [pointsyeah.com](https://www.pointsyeah.com/). Web + iOS + Android. Searches 20+ airline programs (United, Delta, AA, Aeroplan, Flying Blue, ANA, Qantas, etc.) and 5 hotel chains. Free tier: 4-day search window, 4 alerts. Premium: $11.99/mo or $99.99/yr, 8-day window, 32 alerts. Displays cash and award side-by-side. Key UX: "Daydream Explorer" for open-ended destination discovery ([frequentmiler.com](https://frequentmiler.com/pointsyeah/)).

**Data sources.** Confirmed via [AwardWallet](https://awardwallet.com/travel/pointsyeah-review/) reviews and [FlyerTalk threads](https://www.flyertalk.com/forum/travel-tools/2124252-pointsyeah-com-free-all-one-points-travel-planning-award-search-tool.html): they scrape airline loyalty websites in real time, combined with a 60-day cached database. No evidence of GDS/Amadeus use. They publish a per-program status dashboard, implying individual scrapers per airline.

**Pricing.** $11.99/mo or $99.99/yr Premium. No enterprise tier ([apps.apple.com](https://apps.apple.com/us/app/pointsyeah/id6648756794)).

**Company.** Two co-founders, Bart Welch (CEO, Chicago) and Troy Liu (COO, Miami) ([LinkedIn](https://www.linkedin.com/in/bart-welch/), [rocketreach.co](https://rocketreach.co/bart-welch-email_371135046)). $1M seed round. No further funding.

**User complaints** ([Reddit](https://reddit.com), [NerdWallet](https://www.nerdwallet.com/travel/learn/points-yeah-award-search-review-easily-find-your-next-points-redemption), [AwardFares comparison](https://awardfares.com/blog/awardfares-vs-pointsyeah/)):

- Phantom award space: displays as available but not bookable (cached data lag)
- 4-day search window too narrow for power users
- Limited multi-city (2 segments only)
- Aggregated results lack per-program seat counts
- Alert exhaustion: each (date, airport) pair counts separately
- Missing programs: Southwest, BA Avios, Singapore Suites, Qatar QSuites
- App crashes post-update

**Technical gaps exploitable by competitors.**

1. No real-time bookability validation (scrape → cache → alert → seat is gone by the time you click)
2. No per-program seat counts; AwardFares exposes these ([source](https://awardfares.com/blog/awardfares-vs-pointsyeah/))
3. Max 2 flight segments
4. No flex-date alerts ("NA→Europe summer", under threshold)
5. Mobile stability issues suggest under-resourced QA

**Founder note (speculative caution).** In Jun 2024 there was a [Hacker News thread](https://news.ycombinator.com/item?id=40623753) alleging the CEO threatened a CS student's competing tool (FlyMile.pro) with shutdown via a traffic surge + unsolicited calls. Treat as reputational risk for them, not a recommendation to mirror tactics.

**Estimated infra.** $2–5K/mo. Two founders + a couple of engineers. Live scrapes against 20 programs + a Redis-ish cache. Not bootstrap-tiny, not enterprise-scale.

---

## seats.aero

**Product.** Freemium award search at [seats.aero](https://seats.aero/). Free tier: 60-day window. Pro: $9.99/mo or $99.99/yr — year-ahead, direct-only filter, dynamic fares, fee filter ([upgradedpoints.com](https://upgradedpoints.com/news/seats-aero-free-vs-pro/)). Partner API for commercial integrators ([developers.seats.aero](https://developers.seats.aero/reference/getting-started-p)).

**Founder.** Ian Carroll, solo, bootstrapped. Former Staff Security Engineer at Robinhood; security engineer at BitMEX and Dropbox ([LinkedIn](https://www.linkedin.com/in/ian-carroll-a56b8758)). $1.5M ARR ([Boring Cash Cow](https://boringcashcow.com/view/one-man-business-generating-15m-a-year)). No VC, no YC, no co-founders, no employees.

**Architecture (inferred).** Direct web scraping across 24 programs ([liveandletsfly.com](https://liveandletsfly.com/air-canada-lawsuit-seats-aero/), [frequentmiler.com](https://frequentmiler.com/seats-aero/)):
- AA, United, Delta, Southwest, JetBlue, Aeroplan
- Air France-KLM Flying Blue, British Airways, Iberia
- Cathay Pacific, Singapore Airlines, Qatar, Lufthansa
- ANA, JAL, Virgin Atlantic, etc.

Refreshes premium cabins seconds-by-seconds (ANA F, Lufthansa F, Qatar QSuites) per the [comparison](https://awardfares.com/blog/awardfares-vs-seats-aero/). Status page at [seats.aero/status](https://seats.aero/status) shows intermittent outages on newer programs (Qatar Privilege Club in beta, frequent "outage" status), implying active bot-blocking arms races.

**API surface.** Three documented endpoints — Bulk Availability, Get Trips, Live Search — at [developers.seats.aero](https://developers.seats.aero/reference/getting-started-p). Rate limits gated behind login. Live Search requires commercial agreement.

**User sentiment.** Gold-standard reputation on [r/awardtravel](https://nextvacay.substack.com/p/is-seatsaero-worth-it). Occasional false positives on KLM/AF ([NerdWallet](https://nerdwallet.com/travel/learn/seats-aero-review)). Common criticism: expert-only UX; the 60-day free limit is short for planning ([Frequent Miler](https://frequentmiler.com/which-award-search-tool-is-best/)).

**Air Canada lawsuit.** October 2023, federal CFAA + trademark claims ([LoyaltyLobby](https://loyaltylobby.com/2023/10/21/air-canada-sues-award-search-website-seats-aero-in-federal-court-for-computer-fraud-trademark-infringement/), [seats.aero/lawsuit](https://seats.aero/lawsuit)). Seats.aero's defense: scraping public websites is legal. As of writing, still operating.

**The moat.** Network effect (500K+ MAU as crowdsourced demand signal), operational excellence (Ian's security background → infra resilience), data velocity (seconds-level refresh on premium cabins), legal absorption (willing to fight rather than capitulate). The hard parts a hobbyist can't replicate quickly: scraper uptime across 30+ programs, IP rotation infrastructure, sustained legal exposure.

**Hardest airlines to scrape, roughly ordered.** Premium-cabin seats on ANA F, Lufthansa F, Qatar QSuites — minutes-long availability windows. Qatar + Singapore freshly added with frequent outages, implying active blocking. Air Canada has proven litigious. Lufthansa, United, Cathay require IP rotation + UA spoofing. AA and Delta are relatively scraper-friendly.

**Hobbyist replication cost.** ~$50–150/mo cloud infra for IP rotation. 3–6 months solo to stabilize 5 carriers. Tolerable 5–10% false-positive rate. Matching seats.aero's reliability requires professional infra + sustained legal defense.

---

## Open-source projects

| Repo | Stars | Status | Coverage | License | Verdict |
|---|---|---|---|---|---|
| [lg/awardwiz](https://github.com/lg/awardwiz) | 125 | **Archived Sep 2024** | AA, AC, AS, B6, WN, DL (broken), UA (broken) | MIT | Read its Arkalis evasion engine for inspiration. Don't fork. |
| [flightplan-tool/flightplan](https://github.com/flightplan-tool/flightplan) | 153 | Stagnant | AC, AS, BA, CX, KE, NH, SQ | open | Reference for Puppeteer patterns. |
| [timrogers/ba_rewards](https://github.com/timrogers/ba_rewards) | 8 | Maintained, narrow | BA via undocumented iOS Avios Flight Finder API | MIT | **High leverage. Port to Python.** |
| [adamgilman/britishairways-python](https://github.com/adamgilman/britishairways-python) | — | Old | BA | open | Cross-reference for the iOS API endpoint shape. |
| [danielsmith-eu/britishairways-awards-tool](https://github.com/danielsmith-eu/britishairways-awards-tool) | — | Old | BA | open | Same as above. |
| pburka/aeroplanner | 3 | Abandoned | hardcoded YYZ–LHR | — | Skip. |

The bright spot: **`timrogers/ba_rewards`** hits BA's undocumented iOS Avios Flight Finder API. This is dramatically cleaner than scraping the web flow (smaller surface, simpler auth, stabler over time). Porting it to Python is the highest-impact single move available.

Virgin Atlantic: no dedicated scraper. `vseats.io` was a human-run daily scrape. **Uncontested space.**

---

## Strategic takeaways

1. **Web-scraping OSS projects die.** AwardWiz was the best of them and it lost the anti-bot arms race in 2024. Pattern: build on undocumented JSON APIs (BA iOS, AC public award search) when they exist; treat web-scraped carriers as second-class.
2. **The moat for the commercial leaders is data velocity + legal absorption.** Neither is reproducible by a hobbyist. Don't try.
3. **The blind spots are remarkably wide.** Threshold-based alerts, stale-cache re-verification, Discord as primary surface, transfer-bonus math, hackability — none of the commercial tools do any of these.
4. **Dynamic pricing killed fixed-chart tools.** AwardHacker is dead. Our chart-floor providers (AC/BA/VS) are still useful because those three programs still publish saver levels. United/Delta moved off charts entirely — we should not invest in charts for them.
5. **The legal posture matters and is not freely scalable.** seats.aero got sued; Air Canada lost interest before the lawsuit concluded ([per their statement](https://seats.aero/lawsuit)). For a personal-use tool this is a manageable risk; for a distributed SaaS it's not.

---

## Sources (all)

- [seats.aero](https://seats.aero/) · [Boring Cash Cow profile](https://boringcashcow.com/view/one-man-business-generating-15m-a-year) · [seats.aero/lawsuit](https://seats.aero/lawsuit) · [seats.aero/status](https://seats.aero/status) · [LoyaltyLobby on the AC lawsuit](https://loyaltylobby.com/2023/10/21/air-canada-sues-award-search-website-seats-aero-in-federal-court-for-computer-fraud-trademark-infringement/) · [LiveAndLetsFly](https://liveandletsfly.com/air-canada-lawsuit-seats-aero/) · [developers.seats.aero](https://developers.seats.aero/) · [docs.seats.aero](https://docs.seats.aero/article/44-free-vs-pro-what-s-included)
- [pointsyeah.com](https://www.pointsyeah.com/) · [FrequentMiler review](https://frequentmiler.com/pointsyeah/) · [AwardWallet review](https://awardwallet.com/travel/pointsyeah-review/) · [NerdWallet review](https://www.nerdwallet.com/travel/learn/points-yeah-award-search-review-easily-find-your-next-points-redemption) · [Apple App Store](https://apps.apple.com/us/app/pointsyeah/id6648756794) · [FlyerTalk thread](https://www.flyertalk.com/forum/travel-tools/2124252-pointsyeah-com-free-all-one-points-travel-planning-award-search-tool.html)
- [point.me](https://www.point.me/) · [point.me pricing](https://www.point.me/our-services)
- [AwardFares](https://awardfares.com/) · [AwardFares vs PointsYeah](https://awardfares.com/blog/awardfares-vs-pointsyeah/) · [AwardFares vs seats.aero](https://awardfares.com/blog/awardfares-vs-seats-aero/)
- [ExpertFlyer](https://www.expertflyer.com/) · [AwardWallet](https://awardwallet.com/) · [AwardHacker](https://awardhacker.com/)
- GitHub: [lg/awardwiz](https://github.com/lg/awardwiz) · [flightplan-tool/flightplan](https://github.com/flightplan-tool/flightplan) · [timrogers/ba_rewards](https://github.com/timrogers/ba_rewards) · [adamgilman/britishairways-python](https://github.com/adamgilman/britishairways-python) · [danielsmith-eu/britishairways-awards-tool](https://github.com/danielsmith-eu/britishairways-awards-tool)
