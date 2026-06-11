"""v2.a pre-build probe — LLM-driven via Stagehand.

Replaces the selector-based probe (which kept breaking on AC's UI). Drives
the Aeroplan login + award search via natural-language Stagehand `act()`
and `extract()` calls, with Browserbase as the underlying browser and
Claude as the brain.

Goal is identical to the previous probes: verify that an authenticated
Aeroplan session returns real award offers (not a 403 IAM denial). If it
does, v2.a's R2 login driver can be built as Stagehand prompts per
program — ~50 lines apiece — instead of hundreds of lines of selectors.

Required 1Password items (titles tried in order):
  - `Browserbase` with fields `api_key`, `project_id`
  - `www.aircanada.com` (or `Aeroplan`, `aircanada.com`) with `username`,
    `password`, and (optionally) a `one-time-password` / `otp` field
  - `Anthropic` (or `anthropic.com`, `Claude`) with field `api_key`

Run from the terminal that has `op` signed in (stagehand lives in the
`browserbase` optional-dependency group, so the extra is required):

    uv run --extra browserbase python scripts/probe_v2a_aeroplan_stagehand.py

Outputs the final verdict + the path to a JSON dump of intermediate
state in /tmp/v2a-stagehand-result.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ---------- 1Password helpers ----------

BB_ITEM_CANDIDATES = ["Browserbase"]
BB_KEY_FIELDS = ["api_key", "api-key", "apikey", "key"]
BB_PROJECT_FIELDS = ["project_id", "project-id", "projectid", "project"]

AC_ITEM_CANDIDATES = [
    "www.aircanada.com",
    "www.aeroplan.com",
    "aircanada.com",
    "aeroplan.com",
    "Aeroplan",
    "Air Canada",
]
AC_TOTP_FIELDS = ["one-time-password", "otp", "totp"]

ANTHROPIC_ITEM_CANDIDATES = ["Anthropic", "anthropic.com", "Claude", "claude.ai", "Anthropic API"]
ANTHROPIC_KEY_FIELDS = ["api_key", "api-key", "apikey", "key", "credential"]


def _op(item: str, field: str) -> str | None:
    try:
        result = subprocess.run(
            # --reveal is required for concealed fields (e.g. password); without
            # it `op` returns a "[use 'op item get … --reveal' …]" placeholder
            # string instead of the value — which then gets typed as the password.
            ["op", "item", "get", item, "--fields", field, "--reveal"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _try_items(items: list[str], fields: list[str]) -> tuple[str, str] | None:
    """Try (item, field) combinations in nested loop; return (item, value)
    on first success."""
    for item in items:
        for field in fields:
            v = _op(item, field)
            if v:
                return item, v
    return None


def _hydrate_secrets() -> tuple[str, str, str | None]:
    """Read BB + Anthropic creds from 1Password (or env), populate env vars,
    return (ac_username, ac_password, ac_totp) for AC."""
    # Browserbase
    if not (os.getenv("BROWSERBASE_API_KEY") and os.getenv("BROWSERBASE_PROJECT_ID")):
        key_hit = _try_items(BB_ITEM_CANDIDATES, BB_KEY_FIELDS)
        proj_hit = _try_items(BB_ITEM_CANDIDATES, BB_PROJECT_FIELDS)
        if not (key_hit and proj_hit):
            sys.exit(
                "could not load Browserbase creds. Create a 1Password item "
                "titled 'Browserbase' with `api_key` and `project_id` fields, "
                "or set BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID env vars."
            )
        os.environ["BROWSERBASE_API_KEY"] = key_hit[1]
        os.environ["BROWSERBASE_PROJECT_ID"] = proj_hit[1]
        print(f"[op] loaded Browserbase creds from item: {key_hit[0]!r}", flush=True)

    # Anthropic
    if not os.getenv("ANTHROPIC_API_KEY"):
        hit = _try_items(ANTHROPIC_ITEM_CANDIDATES, ANTHROPIC_KEY_FIELDS)
        if not hit:
            sys.exit(
                "could not load Anthropic API key. Create a 1Password item "
                "titled 'Anthropic' with an `api_key` field, "
                "or set ANTHROPIC_API_KEY env var.\n"
                "Get a key from https://console.anthropic.com/settings/keys"
            )
        os.environ["ANTHROPIC_API_KEY"] = hit[1]
        print(f"[op] loaded Anthropic API key from item: {hit[0]!r}", flush=True)

    # AC credentials — env vars win (lets the probe run where `op` isn't
    # available, e.g. a non-interactive subprocess), else fall back to 1Password.
    ac_item: str | None = None
    username = os.getenv("AEROPLAN_USERNAME")
    password = os.getenv("AEROPLAN_PASSWORD")
    totp: str | None = os.getenv("AEROPLAN_TOTP")
    src = "env"
    if not (username and password):
        for item in AC_ITEM_CANDIDATES:
            u = _op(item, "username")
            p = _op(item, "password")
            if u and p:
                ac_item, username, password, src = item, u, p, repr(item)
                break
    if not (username and password):
        sys.exit(
            f"could not load AC credentials. Set AEROPLAN_USERNAME + AEROPLAN_PASSWORD "
            f"env vars, or create a 1Password item (tried {AC_ITEM_CANDIDATES}) with "
            "`username` and `password` fields."
        )
    if totp is None and ac_item is not None:
        for field in AC_TOTP_FIELDS:
            totp = _op(ac_item, field)
            if totp:
                break
    print(f"[op] loaded AC creds from: {src}", flush=True)
    print(f"[op] TOTP available: {bool(totp)}", flush=True)
    return username, password, totp


# Import Stagehand AFTER env hydration so the client constructor sees the keys.
_hydrate_result: tuple[str, str, str | None] | None = None
try:
    _hydrate_result = _hydrate_secrets()
except SystemExit:
    raise

from stagehand import (  # noqa: E402
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    Stagehand,
)

# Stagehand's hosted API occasionally returns transient 5xx / connection blips
# mid-run (a 502 killed the first good probe run). Retry these; never retry 4xx.
_TRANSIENT_ERRORS = (InternalServerError, APITimeoutError, APIConnectionError)

# ---------- Probe ----------

AC_HOMEPAGE = "https://www.aircanada.com/"
# Award search starts from the homepage booking widget. Deep links like
# /aeroplan/use-points/ are marketing hubs and 404 when a search is submitted
# (first probe run died here). The booking widget is the real, authenticated
# entry point to the availability engine.
AC_BOOK_URL = AC_HOMEPAGE
SEARCH_ORIGIN = "YYZ"
SEARCH_DEST = "LHR"
SEARCH_DEPART = (date.today() + timedelta(days=120)).isoformat()
MODEL_NAME = "anthropic/claude-sonnet-4-5-20250929"
# Residential-proxy geolocation for the Browserbase session (Kasada bypass).
# US to match the repo's award-search defaults (providers/_browserbase.py).
PROXY_COUNTRY = "us"

RESULT_OUT = Path("/tmp/v2a-stagehand-result.json")


# Secret values registered here are redacted from all log output. Populated in
# main() after hydration so credentials never get printed (the env-var path
# would otherwise log the password verbatim in the fill instruction).
_SECRETS: list[str] = []


def _scrub(text: str) -> str:
    for s in _SECRETS:
        if s:
            text = text.replace(s, "***")
    return text


def _log(stage: str, msg: str) -> None:
    print(f"[{stage}] {_scrub(msg)}", flush=True)


def _retry(what: str, fn: Any, attempts: int = 3) -> Any:
    """Call `fn`, retrying transient 5xx/connection errors with backoff."""
    delay = 2.0
    for i in range(1, attempts + 1):
        try:
            return fn()
        except _TRANSIENT_ERRORS as e:
            if i == attempts:
                _log(what, f"  giving up after {attempts} attempts: {type(e).__name__}: {str(e)[:160]}")
                raise
            _log(what, f"  transient {type(e).__name__} (attempt {i}/{attempts}); retrying in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
        except Exception as e:
            _log(what, f"  ERROR: {type(e).__name__}: {str(e)[:200]}")
            raise


def _act(client: Stagehand, sid: str, instruction: str) -> Any:
    """Wrapper that logs the instruction + returns the response."""
    _log("act", instruction[:120])
    return _retry("act", lambda: client.sessions.act(id=sid, input=instruction))


def _extract(client: Stagehand, sid: str, instruction: str, schema: dict[str, Any]) -> Any:
    _log("extract", instruction[:120])
    return _retry(
        "extract",
        lambda: client.sessions.extract(id=sid, instruction=instruction, schema=schema),
    )


def _result_dict(resp: Any) -> dict[str, Any]:
    """Normalize a Stagehand extract response to the extracted payload dict.

    `client.sessions.extract()` returns a `SessionExtractResponse` whose shape
    is `.data` (a `Data` model) -> `.result` (the schema-matched payload). Both
    levels must be unwrapped: stopping at `.data` and model_dump-ing it yields
    `{'result': {...}, 'action_id': ...}` instead of the payload — the bug that
    made the login gate and classifier read `None` for every field. Each of the
    two unwraps is independent so a bare `Data` or a plain dict also works.
    """
    inner = resp
    if hasattr(inner, "data"):
        inner = inner.data
    if hasattr(inner, "result"):
        inner = inner.result
    if hasattr(inner, "model_dump"):
        inner = inner.model_dump()
    return inner if isinstance(inner, dict) else {}


def main() -> None:
    assert _hydrate_result is not None
    username, password, totp = _hydrate_result
    _SECRETS.extend(s for s in (password, totp) if s)  # redact from all logs

    client = Stagehand(
        browserbase_api_key=os.environ["BROWSERBASE_API_KEY"],
        browserbase_project_id=os.environ["BROWSERBASE_PROJECT_ID"],
        model_api_key=os.environ["ANTHROPIC_API_KEY"],
    )

    _log("stagehand", f"starting session with model {MODEL_NAME}")
    # AC is protected by Kasada — a vanilla browser submits the login form and
    # silently stays put (no error). solve_captchas does NOT help: Kasada shows
    # no visible CAPTCHA (it's a proof-of-work JS challenge + TLS/behavioral
    # fingerprint). Browserbase's one lever that *can* clear it is "Verified
    # browsers" (browser_settings.verified=True) — a purpose-built Chromium with
    # fingerprints its bot-protection partners recognize. Verified is Scale-plan
    # gated, so we try it first and fall back to standard stealth (residential
    # proxy + solve_captchas) if the plan rejects it. Toggle off with V2A_VERIFIED=0.
    def _start(verified: bool) -> Any:
        bs: dict[str, Any] = {"solve_captchas": True}
        if verified:
            bs["verified"] = True
        return client.sessions.start(
            model_name=MODEL_NAME,
            verbose=1,
            self_heal=True,
            wait_for_captcha_solves=True,
            browserbase_session_create_params={
                "project_id": os.environ["BROWSERBASE_PROJECT_ID"],
                "proxies": [{"type": "browserbase", "geolocation": {"country": PROXY_COUNTRY}}],
                "browser_settings": bs,
            },
        )

    want_verified = os.getenv("V2A_VERIFIED", "1") != "0"
    stealth_mode = "standard"
    if want_verified:
        try:
            session = _start(verified=True)
            stealth_mode = "verified"
        except Exception as e:
            _log("stagehand", f"verified-mode session rejected ({type(e).__name__}: {str(e)[:160]}); "
                              "falling back to standard stealth (residential proxy + solve_captchas)")
            session = _start(verified=False)
    else:
        session = _start(verified=False)
    sid = session.id
    _log("stagehand", f"session started: {sid} (stealth={stealth_mode})")

    trace: list[dict[str, Any]] = []
    verdict = "PROBE_INCONCLUSIVE"
    reason = "did not reach classification"

    try:
        # ---- Stage 1: navigate + sign in ----
        _log("nav", f"navigating to {AC_HOMEPAGE}")
        client.sessions.navigate(id=sid, url=AC_HOMEPAGE)

        _act(client, sid, "If a cookie consent or privacy banner is visible, dismiss it by accepting cookies. If no banner is visible, do nothing.")

        _act(client, sid, "Find and click the 'Sign in' link or button. It may be in the top navigation, behind a 'My profile' menu, or near the top-right of the page.")
        _act(client, sid, "Wait for the sign-in form, with an 'Aeroplan number or email' field and a 'Password' field, to be fully visible.")

        # Fill + verify before submitting. AC's form re-renders during load and a
        # too-early fill gets cleared, producing a "Please enter your Aeroplan
        # Number or Email" validation on submit (the failure in probe run 2).
        for attempt in range(1, 4):
            _act(client, sid, f"Click the 'Aeroplan number or email' field (the username/email input) and type exactly: {username}")
            _act(client, sid, f"Click the 'Password' field and type exactly: {password}")
            filled = _result_dict(_extract(
                client,
                sid,
                "Report whether BOTH the 'Aeroplan number or email' field and the 'Password' field currently contain text (are non-empty). Set fields_filled=true only if both have values.",
                {
                    "type": "object",
                    "properties": {
                        "fields_filled": {"type": "boolean"},
                        "detail": {"type": "string"},
                    },
                    "required": ["fields_filled"],
                },
            ))
            if filled.get("fields_filled", False):
                break
            _log("login", f"credentials not filled (attempt {attempt}/3): {filled.get('detail', '')!r}; retrying")

        # ---- Stage 2: submit + confirm login (with retry) ----
        # A filled form that never authenticates (login_succeeded stays false
        # with no error) means the submit click didn't take. Retry the submit a
        # different way (Enter key) and re-check, rather than charging ahead.
        login_detect = (
            "Describe what is currently on the page. Report login_succeeded=true ONLY if we "
            "are signed in (an account/profile menu, member name, sign-out option, or a "
            "logged-in dashboard is visible) — login_succeeded=false if a login form with "
            "email/password fields is still showing. Also detect whether a multi-factor "
            "authentication challenge is shown (verification code input, push approval, etc.) "
            "and its kind. Capture any visible error message."
        )
        login_schema = {
            "type": "object",
            "properties": {
                "page_summary": {"type": "string"},
                "login_succeeded": {"type": "boolean"},
                "mfa_required": {"type": "boolean"},
                "mfa_type": {
                    "type": "string",
                    "enum": ["totp_or_code", "email_code", "push_approve", "none", "unknown"],
                },
                "errors_visible": {"type": "string"},
            },
            "required": ["page_summary", "mfa_required"],
        }

        data: dict[str, Any] = {}
        for submit_attempt in range(1, 3):
            if submit_attempt == 1:
                _act(client, sid, "Click the 'Sign in' submit button at the bottom of the login form itself (the form's own button — NOT a navigation menu link or header) to log in.")
            else:
                _act(client, sid, "The login form is still showing. Click into the 'Password' field and press the Enter key to submit the login form.")
            _act(client, sid, "Wait for the page to finish loading after submitting the login form. If a verification/MFA screen, an account dashboard, or the Air Canada homepage appears, stop waiting.")

            data = _result_dict(_extract(client, sid, login_detect, login_schema))
            trace.append({"stage": f"post_login_detect_{submit_attempt}", "result": data})
            _log("mfa", f"submit attempt {submit_attempt}: {data}")
            if data.get("login_succeeded") or data.get("mfa_required"):
                break
            _log("login", f"login not confirmed after submit attempt {submit_attempt}; errors={data.get('errors_visible', '')!r}")

        # ---- Stage 3: handle MFA if any ----
        if isinstance(data, dict) and data.get("mfa_required"):
            mfa_type = data.get("mfa_type", "unknown")
            if mfa_type in ("totp_or_code",) and totp:
                _log("mfa", "using TOTP from 1Password")
                code = totp
            elif mfa_type == "push_approve":
                _log("mfa", "PUSH-style MFA — approve on your phone, then press Enter here")
                input()
                code = None
            else:
                code = input(f"enter MFA code ({mfa_type}): ").strip()
            if code:
                _act(client, sid, f"Fill the verification code or OTP input with the value: {code}, then click the Verify or Submit or Continue button.")

        # Gate: if login plainly failed (still on the form, no MFA pending),
        # bail with a clear verdict instead of running a doomed unauth search.
        if data.get("login_succeeded") is False and not data.get("mfa_required"):
            verdict = "PROBE_INCONCLUSIVE"
            reason = (
                "Login did not complete — still on the sign-in form "
                f"(error: {data.get('errors_visible', '') or 'none reported'!r}). "
                "The auth-session-vs-IAM question is still UNTESTED. Fix the login "
                "flow (credential fill / submit) and re-run before drawing conclusions."
            )
            _log("login", "login failed — skipping search; nothing to learn from an unauthenticated search")
            return

        # ---- Stage 4: award search via the homepage booking widget ----
        _log("nav", f"navigating to {AC_BOOK_URL}")
        client.sessions.navigate(id=sid, url=AC_BOOK_URL)

        _act(client, sid, "On the flight booking search widget, choose to book/pay with Aeroplan points. There is usually a toggle, switch, or radio button labelled 'Book with points', 'Use points', or 'Aeroplan points' — enable it. If no such control exists, do nothing.")
        _act(client, sid, "Set the trip type to one-way.")
        _act(
            client,
            sid,
            f"In the booking widget, set the origin/from airport to {SEARCH_ORIGIN} and the destination/to airport to "
            f"{SEARCH_DEST}. Set the departure date to {SEARCH_DEPART}. Set cabin to Business and passengers to 1 adult.",
        )
        _act(client, sid, "Click the search, find flights, or submit button to run the award flight search.")

        _act(client, sid, "Wait for the flight search results to fully load. If a loading spinner is visible, wait until it disappears.")

        # ---- Stage 5: extract result + classify ----
        results = _extract(
            client,
            sid,
            "Extract whether the search returned actual flight options. Return offers_found=true ONLY if there are at least one bookable flight option visible with a points cost. If an error message, 403 forbidden, IAM denial, or 'unable to load' message is shown, capture it.",
            {
                "type": "object",
                "properties": {
                    "offers_found": {"type": "boolean"},
                    "offer_count": {"type": "integer"},
                    "first_offer_summary": {"type": "string"},
                    "error_or_block_message": {"type": "string"},
                    "page_url": {"type": "string"},
                },
                "required": ["offers_found"],
            },
        )
        rdata = _result_dict(results)
        trace.append({"stage": "search_extract", "result": rdata})
        _log("results", f"{rdata}")

        if isinstance(rdata, dict):
            offers_found = bool(rdata.get("offers_found"))
            offer_count = int(rdata.get("offer_count") or 0)
            err = str(rdata.get("error_or_block_message") or "").lower()

            if offers_found and offer_count > 0:
                verdict = "PROBE_PASSES"
                reason = (
                    f"Authenticated session returned {offer_count} offer(s). "
                    f"Sample: {rdata.get('first_offer_summary', '?')}. "
                    "v2.a hypothesis verified; proceed to /ce-plan."
                )
            elif "forbidden" in err or "explicit deny" in err or "403" in err or "denied" in err:
                verdict = "PROBE_FAILS"
                reason = (
                    f"Auth session still blocked at search level: {err[:200]}. "
                    "v2.a's auth-session approach does not clear AC's IAM. "
                    "Likely paths: scrape rendered DOM, use iOS app, drop AC."
                )
            elif "404" in err or "flown away" in err or "sign in" in err or "log in" in err or "session" in err:
                verdict = "PROBE_INCONCLUSIVE"
                reason = (
                    f"Search did not reach the availability engine: {err[:200]}. "
                    "Likely the booking widget wasn't driven correctly or the "
                    f"session bounced to login. Inspect trace: {RESULT_OUT}"
                )
            elif offers_found:
                verdict = "PROBE_INCONCLUSIVE"
                reason = (
                    f"offers_found=true but offer_count is 0. LLM saw something "
                    f"but counted nothing. Inspect trace: {RESULT_OUT}"
                )
            else:
                verdict = "PROBE_INCONCLUSIVE"
                reason = (
                    f"No offers found, no clear error. Likely: no availability "
                    f"for this date/cabin (try a different date), or the search "
                    f"didn't actually submit. Inspect trace: {RESULT_OUT}"
                )

    finally:
        _log("stagehand", "ending session")
        try:
            client.sessions.end(id=sid)
        except Exception as e:
            _log("stagehand", f"end raised: {type(e).__name__}: {e}")

        # Sanitize trace: don't dump cookies/JWTs into the result file
        RESULT_OUT.write_text(
            json.dumps({"verdict": verdict, "reason": reason, "trace": trace}, indent=2, default=str)
        )

        print()
        print("=" * 60)
        print(f"VERDICT: {verdict}")
        print(f"REASON:  {reason}")
        print(f"TRACE:   {RESULT_OUT}")
        print("=" * 60)


if __name__ == "__main__":
    main()
