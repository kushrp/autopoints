"""v2.a probe — human-assisted login, then automated award search.

Fully-automated AC login is Kasada-walled: with the real password + a
Browserbase residential proxy the sign-in form silently refuses to submit
(see scripts/probe_v2a_aeroplan_stagehand.py). This variant pivots to the
v2.a `SessionManager` model:

  1. Create a stealth Browserbase session (residential proxy + captcha solve),
     kept alive so it survives a manual login.
  2. Print the live-view URL. YOU open it and sign in to Aeroplan by hand,
     clearing Kasada the way a real browser does.
  3. Capture the authenticated cookies/storage (foundation for v2.a session
     persistence) to /tmp/v2a-session-cookies.json.
  4. Attach Stagehand to the now-authenticated session and run the award
     search — answering the question v2.a rides on: does an authenticated
     session clear Air Canada's IAM "explicit deny", or not?

This script is INTERACTIVE — run it in a terminal where you can open a URL and
press Enter. Credentials load from 1Password (`op`) or env vars; AC creds are
NOT required here (you type them into the live view yourself).

    uv run --extra browserbase python scripts/probe_v2a_human_login.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ---------- 1Password / env hydration (Browserbase + Anthropic only) ----------

BB_ITEM_CANDIDATES = ["Browserbase"]
BB_KEY_FIELDS = ["api_key", "api-key", "apikey", "key"]
BB_PROJECT_FIELDS = ["project_id", "project-id", "projectid", "project"]
ANTHROPIC_ITEM_CANDIDATES = ["Anthropic", "anthropic.com", "Claude", "claude.ai", "Anthropic API"]
ANTHROPIC_KEY_FIELDS = ["api_key", "api-key", "apikey", "key", "credential"]


def _op(item: str, field: str) -> str | None:
    try:
        result = subprocess.run(
            ["op", "item", "get", item, "--fields", field, "--reveal"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return result.stdout.strip() or None if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _try_items(items: list[str], fields: list[str]) -> str | None:
    for item in items:
        for field in fields:
            v = _op(item, field)
            if v:
                return v
    return None


def _hydrate() -> None:
    if not (os.getenv("BROWSERBASE_API_KEY") and os.getenv("BROWSERBASE_PROJECT_ID")):
        key = _try_items(BB_ITEM_CANDIDATES, BB_KEY_FIELDS)
        proj = _try_items(BB_ITEM_CANDIDATES, BB_PROJECT_FIELDS)
        if not (key and proj):
            sys.exit("could not load Browserbase creds (1Password item 'Browserbase' or "
                     "BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID env vars).")
        os.environ["BROWSERBASE_API_KEY"] = key
        os.environ["BROWSERBASE_PROJECT_ID"] = proj
    if not os.getenv("ANTHROPIC_API_KEY"):
        key = _try_items(ANTHROPIC_ITEM_CANDIDATES, ANTHROPIC_KEY_FIELDS)
        if not key:
            sys.exit("could not load Anthropic API key (1Password item 'Anthropic' or "
                     "ANTHROPIC_API_KEY env var).")
        os.environ["ANTHROPIC_API_KEY"] = key


_hydrate()

from browserbase import Browserbase  # noqa: E402
from stagehand import Stagehand  # noqa: E402

# ---------- config ----------

AC_HOMEPAGE = "https://www.aircanada.com/"
SEARCH_ORIGIN = "YYZ"
SEARCH_DEST = "LHR"
SEARCH_DEPART = (date.today() + timedelta(days=120)).isoformat()
MODEL_NAME = "anthropic/claude-sonnet-4-5-20250929"
PROXY_COUNTRY = "us"
COOKIES_OUT = Path("/tmp/v2a-session-cookies.json")
RESULT_OUT = Path("/tmp/v2a-human-login-result.json")


def _log(stage: str, msg: str) -> None:
    print(f"[{stage}] {msg}", flush=True)


def _result_dict(resp: Any) -> dict[str, Any]:
    inner = resp
    if hasattr(inner, "data"):
        inner = inner.data
    if hasattr(inner, "result"):
        inner = inner.result
    if hasattr(inner, "model_dump"):
        inner = inner.model_dump()
    return inner if isinstance(inner, dict) else {}


def _prime(connect_url: str) -> None:
    """Best-effort: land the session on the AC homepage so the live view is
    ready for the user to click 'Sign in'. Non-fatal."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(connect_url)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(AC_HOMEPAGE, wait_until="domcontentloaded", timeout=45000)
            browser.close()
    except Exception as e:
        _log("prime", f"pre-navigation skipped (non-fatal): {type(e).__name__}: {str(e)[:120]}")


def _capture_cookies(connect_url: str) -> int:
    """Best-effort: dump the authenticated session's cookies via CDP. Non-fatal.
    Returns the cookie count (0 on failure)."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(connect_url)
            ctx = browser.contexts[0]
            cookies = ctx.cookies()
            COOKIES_OUT.write_text(json.dumps(cookies, indent=2))
            browser.close()
            return len(cookies)
    except Exception as e:
        _log("cookies", f"capture failed (non-fatal): {type(e).__name__}: {str(e)[:160]}")
        return 0


def main() -> None:
    bb = Browserbase(api_key=os.environ["BROWSERBASE_API_KEY"])

    _log("bb", "creating stealth session (residential proxy + captcha solve, keep-alive)")
    session = bb.sessions.create(
        project_id=os.environ["BROWSERBASE_PROJECT_ID"],
        keep_alive=True,
        proxies=[{"type": "browserbase", "geolocation": {"country": PROXY_COUNTRY}}],
        browser_settings={"solveCaptchas": True},
    )
    _log("bb", f"session: {session.id}")

    _prime(session.connect_url)
    live = bb.sessions.debug(session.id)
    url = getattr(live, "debugger_fullscreen_url", None) or getattr(live, "debugger_url", None)

    # --- Stagehand attaches up front: used both to poll for the login and to
    #     run the search. Until login is confirmed it only does read-only
    #     extract() calls, so it won't disturb the manual sign-in happening in
    #     the same live-view session. ---
    verdict = "PROBE_INCONCLUSIVE"
    reason = "did not reach classification"
    trace: list[dict[str, Any]] = []

    _log("stagehand", "attaching to the session (read-only until login confirmed)")
    client = Stagehand(
        browserbase_api_key=os.environ["BROWSERBASE_API_KEY"],
        browserbase_project_id=os.environ["BROWSERBASE_PROJECT_ID"],
        model_api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    sh = client.sessions.start(
        model_name=MODEL_NAME,
        verbose=1,
        self_heal=True,
        wait_for_captcha_solves=True,
        browserbase_session_id=session.id,
    )
    sid = sh.id

    def act(instr: str) -> None:
        _log("act", instr[:120])
        client.sessions.act(id=sid, input=instr)

    def extract(instr: str, schema: dict[str, Any]) -> dict[str, Any]:
        _log("extract", instr[:120])
        return _result_dict(client.sessions.extract(id=sid, instruction=instr, schema=schema))

    AUTH_INSTR = (
        "Report login_succeeded=true ONLY if the page shows a signed-in state "
        "(account/profile menu, member name, or sign-out option). false if a login "
        "form is showing."
    )
    AUTH_SCHEMA = {
        "type": "object",
        "properties": {
            "login_succeeded": {"type": "boolean"},
            "page_summary": {"type": "string"},
        },
        "required": ["login_succeeded"],
    }

    print("\n" + "=" * 70)
    print("HUMAN LOGIN STEP")
    print("=" * 70)
    print("1. Open this live-view URL in your browser:\n")
    print(f"   {url}\n")
    print(f"2. Go to {AC_HOMEPAGE} (or it may already be open), click Sign in,")
    print("   and log in to your Aeroplan account BY HAND (clears Kasada).")
    print("=" * 70, flush=True)

    # Interactive terminal -> wait for Enter. Launched unattended (no TTY, or
    # V2A_POLL_LOGIN=1) -> poll the page until the signed-in state shows up.
    interactive = sys.stdin.isatty() and os.getenv("V2A_POLL_LOGIN") != "1"
    auth: dict[str, Any] = {}
    try:
        if interactive:
            print("3. Once signed in, come back here and press Enter.", flush=True)
            input("\nPress Enter once you are logged in… ")
            auth = extract(AUTH_INSTR, AUTH_SCHEMA)
        else:
            import time

            timeout_s = int(os.getenv("V2A_LOGIN_TIMEOUT", "420"))
            interval_s = int(os.getenv("V2A_LOGIN_POLL_INTERVAL", "30"))
            _log("poll", f"unattended: polling for manual login up to {timeout_s}s (every {interval_s}s)")
            waited = 0
            while waited < timeout_s:
                time.sleep(interval_s)
                waited += interval_s
                auth = extract(AUTH_INSTR, AUTH_SCHEMA)
                _log("poll", f"t={waited}s login_succeeded={auth.get('login_succeeded')}")
                if auth.get("login_succeeded"):
                    break
    except (EOFError, KeyboardInterrupt):
        _log("bb", "aborted before login; ending session")
        try:
            client.sessions.end(id=sid)
        except Exception:
            pass
        bb.sessions.update(session.id, project_id=os.environ["BROWSERBASE_PROJECT_ID"], status="REQUEST_RELEASE")
        sys.exit("aborted")

    n = _capture_cookies(session.connect_url)
    _log("cookies", f"captured {n} cookies -> {COOKIES_OUT}" if n else "no cookies captured")

    try:
        trace.append({"stage": "auth_check", "result": auth})
        _log("auth", f"{auth}")
        if not auth.get("login_succeeded"):
            verdict = "PROBE_INCONCLUSIVE"
            reason = ("Never detected a signed-in Aeroplan state. Re-run and finish the login in "
                      "the live-view; raise V2A_LOGIN_TIMEOUT if you need more time.")
            return

        # Award search via the homepage booking widget.
        _log("nav", f"navigating to {AC_HOMEPAGE}")
        client.sessions.navigate(id=sid, url=AC_HOMEPAGE)
        act("On the flight booking search widget, choose to book/pay with Aeroplan points "
            "(enable any 'Book with points' / 'Use points' toggle). If none exists, do nothing.")
        act("Set the trip type to one-way.")
        act(f"Set the origin/from airport to {SEARCH_ORIGIN}, the destination/to airport to "
            f"{SEARCH_DEST}, the departure date to {SEARCH_DEPART}, cabin to Business, 1 adult.")
        act("Click the search / find flights / submit button to run the award search.")
        act("Wait for the flight results to fully load; if a spinner is visible, wait for it to clear.")

        results = extract(
            "Extract whether the award search returned bookable flight options. offers_found=true "
            "ONLY if at least one bookable flight option with a points cost is visible. If an error, "
            "403 forbidden, IAM denial, or 'unable to load' is shown, capture it verbatim.",
            {
                "type": "object",
                "properties": {
                    "offers_found": {"type": "boolean"},
                    "offer_count": {"type": "integer"},
                    "first_offer_summary": {"type": "string"},
                    "error_or_block_message": {"type": "string"},
                },
                "required": ["offers_found"],
            },
        )
        trace.append({"stage": "search", "result": results})
        _log("results", f"{results}")

        offers = bool(results.get("offers_found"))
        count = int(results.get("offer_count") or 0)
        err = str(results.get("error_or_block_message") or "").lower()
        if offers and count > 0:
            verdict = "PROBE_PASSES"
            reason = (f"Authenticated session returned {count} award offer(s) "
                      f"(sample: {results.get('first_offer_summary', '?')}). v2.a hypothesis "
                      "VERIFIED — a human-login session clears AC's IAM. Proceed to /ce-plan.")
        elif any(k in err for k in ("forbidden", "explicit deny", "403", "denied", "iam")):
            verdict = "PROBE_FAILS"
            reason = (f"Even an authenticated (human-login) session is blocked: {err[:200]}. "
                      "The IAM deny is not about anonymous identity — auth doesn't clear it. "
                      "Rethink v2.a (DOM scrape of rendered results, iOS app, or drop AC).")
        else:
            verdict = "PROBE_INCONCLUSIVE"
            reason = (f"No offers and no clear block (err={err[:120]!r}). Likely no availability "
                      f"for {SEARCH_DEPART} in Business, or the widget search didn't submit. "
                      "Try a different date/cabin or inspect the live view.")
    finally:
        try:
            client.sessions.end(id=sid)
        except Exception:
            pass
        # Release the keep-alive Browserbase session so it doesn't linger/bill.
        try:
            bb.sessions.update(session.id, project_id=os.environ["BROWSERBASE_PROJECT_ID"], status="REQUEST_RELEASE")
        except Exception:
            pass
        RESULT_OUT.write_text(json.dumps({"verdict": verdict, "reason": reason, "trace": trace}, indent=2, default=str))
        print("\n" + "=" * 70)
        print(f"VERDICT: {verdict}")
        print(f"REASON:  {reason}")
        print(f"TRACE:   {RESULT_OUT}   COOKIES: {COOKIES_OUT}")
        print("=" * 70)


if __name__ == "__main__":
    main()
