# Live checks

The regular `pytest` suite runs 111 mocked unit tests (`addopts = "-m 'not e2e'"`).
That catches logic regressions but tells you nothing about whether the *real*
Google Flights / Aeroplan / Browserbase / Discord endpoints are still reachable.

`scripts/check_live.py` fills that gap: one command, one report, every
shipped feature against its real backend.

## Run locally

```bash
uv run scripts/check_live.py                    # full suite
uv run scripts/check_live.py --only google_flights_redeye_lax_jfk
uv run scripts/check_live.py --json out.json    # machine-readable too
```

Each check is independent. Missing a secret? That check **skips** cleanly —
the rest still run. Final summary line is `N pass / M fail / K skip`; exit
code is `1` iff any check failed (skips do not fail the run).

## What each check verifies

| Check | What it proves | Secrets |
|---|---|---|
| `orchestrator_arrive_before_demo` | Demo cash provider + static charts + CPP build + `--arrive-before` filter all wire up end-to-end. | none |
| `google_flights_redeye_lax_jfk` | `fli` still talks to Google's backend and returns at least one redeye for LAX→JFK. | none |
| `aeroplan_handshake_reaches_air_bounds` | Cognito identity exchange + SigV4 signing + market-token POST all succeed; the call reaches Kasada. **A Kasada 429 is the PASS.** See below. | none (or `AEROPLAN_API_KEY` if rotated) |
| `browserbase_session_creates` | API key + project ID are valid, Browserbase issues a session, Playwright connects over CDP. | `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` |
| `discord_bot_can_reach_channel` | Bot token is valid, can connect to the gateway, post an embed to the test channel, and delete it. | `DISCORD_BOT_TOKEN`, `DISCORD_TEST_CHANNEL_ID` |

Order is cheapest-first: a quick fail in `orchestrator_arrive_before_demo` or
`google_flights_redeye_lax_jfk` surfaces fast before the slow Browserbase /
Discord round-trips burn time.

## "Kasada-blocked as expected" — why a failure is a pass

The Aeroplan endpoint (`akamai-gw.dbaas.aircanada.com`) sits behind Kasada bot
management on production traffic. Any server-side signed request — including
ours — gets HTTP 429 with `x-kpsdk-ct` headers. This is documented in
`docs/probes/v1c-aeroplan-endpoint-discovery.md` and is exactly why the
phase-2 follow-up (v1.c-2) routes the call through Browserbase.

What the live check is really validating is the **handshake before** Kasada:

1. Cognito `GetCredentialsForIdentity` exchange
2. SigV4 signing of the market-token POST
3. Market-token endpoint accepting the signed request

If any of those three steps regressed, the `ProviderError` would mention
*Cognito* or *market-token* or *SigV4*, not Kasada. The check passes only
when the error string contains `Kasada` or `429` — proof the handshake
reached the bot-blocked layer.

If Kasada is ever disabled or the path changes, the check still passes but
the detail line says `no Kasada block — got N offers (investigate)`. That's
a green light worth looking at: it means the v1.c-2 Browserbase rewrite may
no longer be needed.

## Setting secrets in GitHub

Repo → Settings → Secrets and variables → Actions → New repository secret.

Required for full coverage:

- `BROWSERBASE_API_KEY`
- `BROWSERBASE_PROJECT_ID`
- `DISCORD_BOT_TOKEN`
- `DISCORD_TEST_CHANNEL_ID` — a channel the bot has Send Messages + Manage
  Messages permission on. Pick a hidden dev channel; the bot posts a tiny
  embed and immediately deletes it.

Optional:

- `AEROPLAN_API_KEY` — only set if the hard-coded default in
  `autopoints/providers/aeroplan.py` has rotated again.
- `SLACK_WEBHOOK_URL` or `NOTIFY_DISCORD_WEBHOOK` — incoming webhook for
  failure pings. Workflow no-ops when unset.

## Schedule

`.github/workflows/live-checks.yml` runs on cron `0 7 * * 0` (Sundays 07:00
UTC). Manual runs via the Actions tab → Run workflow, with an optional
`only` input for ad-hoc single-check runs.

Reports upload as the `live-report` artifact (JSON) on every run, success or
failure, so historical baselines are reviewable.

## Adding a new check

1. Write `async def check_<name>() -> CheckOutcome` in
   `scripts/check_live.py`. Use the `_skip` / `_pass` / `_fail` helpers.
2. Append it to the `CHECKS` list — order = run order.
3. If the feature also has a unit test that hits real network, mark the
   live one `@pytest.mark.e2e` so the default suite skips it (the existing
   `tests/test_google_flights.py::test_live_lax_jfk_returns_redeye` is the
   reference pattern).
4. Add required secrets to the workflow's `env:` block and document them
   above.
