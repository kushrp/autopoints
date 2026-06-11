"""v2.a pre-build probe: does an authenticated Aeroplan session clear the IAM
denial we hit in PR #9?

Procedure: user captures real session headers from DevTools after a manual
search on aircanada.com, pastes them into the JSON file referenced below,
and runs this script. We POST to the air-bounds endpoint with those headers
and a known-good search body, then report the verdict.

This is intentionally NOT integrated into AeroplanProvider — no codebase
side-effects, no committed credentials, easy to delete after we have the
answer. The file path under /tmp is gitignored by location.

Usage:
    1. Capture headers per docs/probes/v2a-aeroplan-session-probe.md
    2. Save them as JSON at /tmp/aeroplan-probe-headers.json
    3. uv run python scripts/probe_v2a_aeroplan_session.py

The script never logs the raw headers or response cookies. Output is
verdict + status code + truncated body snippet only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import httpx

from autopoints.providers.aeroplan import (
    _AIR_BOUNDS_ENDPOINT,
    AeroplanProvider,
)

HEADERS_PATH = Path("/tmp/aeroplan-probe-headers.json")

# A known-good search shape. YYZ -> LHR, business class, ~4 months out so
# saver availability is likely to exist.
PROBE_ORIGIN = "YYZ"
PROBE_DEST = "LHR"
PROBE_DATE = date(2026, 10, 15)
PROBE_CABIN_HINT = "business"


def _load_headers() -> dict[str, str]:
    if not HEADERS_PATH.exists():
        sys.exit(
            f"ERROR: {HEADERS_PATH} does not exist.\n"
            f"Capture headers per docs/probes/v2a-aeroplan-session-probe.md "
            f"and write them as JSON to that path."
        )
    raw = json.loads(HEADERS_PATH.read_text())
    if not isinstance(raw, dict):
        sys.exit(f"ERROR: {HEADERS_PATH} must contain a JSON object of header_name -> value.")
    # Require at minimum a Cookie header — without it we don't have a session.
    cookie_keys = [k for k in raw if k.lower() == "cookie"]
    if not cookie_keys:
        sys.exit(
            "ERROR: no Cookie header in the JSON. The whole point of this "
            "probe is to test the captured session — without Cookie there's "
            "no session to test."
        )
    return {str(k): str(v) for k, v in raw.items()}


def _classify_response(status: int, body: str) -> tuple[str, str]:
    """Return (verdict, human_message)."""
    if status == 200:
        try:
            data = json.loads(body)
            groups = data.get("data", {}).get("airBoundGroups", [])
            if groups:
                return (
                    "PROBE_PASSES",
                    f"200 OK + {len(groups)} airBoundGroup(s). The hypothesis "
                    f"is real — authenticated sessions clear the IAM wall. "
                    f"v2.a proceeds.",
                )
            return (
                "PROBE_INCONCLUSIVE",
                "200 OK but no airBoundGroups in the response. Either "
                "there's genuinely no availability for this date/cabin (try "
                "another), or the response shape changed since v1.c-1. "
                "Inspect body below.",
            )
        except json.JSONDecodeError:
            return (
                "PROBE_INCONCLUSIVE",
                "200 OK but body isn't JSON. Likely a Kasada interstitial "
                "or a redirect page. Inspect body below.",
            )
    if status == 403:
        if "explicit deny" in body.lower() or "identity-based policy" in body.lower():
            return (
                "PROBE_FAILS",
                "403 with IAM explicit-deny — same wall PR #9 hit. The "
                "authenticated session ALSO does not have market-token "
                "permission. The whole v2.a bet is invalidated; rethink "
                "before scoping further. Likely paths: scrape rendered "
                "results from the booking page DOM, use the iOS app, or "
                "drop Aeroplan from scope.",
            )
        return (
            "PROBE_FAILS",
            "403, but not the IAM-deny shape. Could be an authorization "
            "header binding (e.g., AC expects a freshly-minted token, not "
            "a captured one). Inspect body below.",
        )
    if status == 429:
        return (
            "PROBE_INCONCLUSIVE",
            "429 — Kasada-shaped block. The captured cookies didn't carry "
            "a fresh Kasada token, or AC rotated since you captured. Re-do "
            "the capture flow and re-run.",
        )
    if status in (401,):
        return (
            "PROBE_INCONCLUSIVE",
            "401 — captured session was invalid or expired between capture "
            "and probe. Re-capture (log out + back in to refresh) and rerun.",
        )
    return (
        "PROBE_INCONCLUSIVE",
        f"Unexpected status {status}. Inspect body below to classify.",
    )


async def main() -> None:
    headers = _load_headers()
    provider = AeroplanProvider()
    body = provider._build_search_body(  # type: ignore[attr-defined]
        PROBE_ORIGIN, PROBE_DEST, PROBE_DATE, passengers=1
    )

    print("=== v2.a Aeroplan session probe ===")
    print(f"target:  {PROBE_ORIGIN} -> {PROBE_DEST} on {PROBE_DATE.isoformat()}")
    print(f"endpoint: {_AIR_BOUNDS_ENDPOINT}")
    print(f"header keys (values redacted): {sorted(headers.keys())}")
    print()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(_AIR_BOUNDS_ENDPOINT, headers=headers, json=body)
        except httpx.HTTPError as e:
            sys.exit(f"network error firing probe: {e}")

    verdict, message = _classify_response(resp.status_code, resp.text)
    print(f"verdict: {verdict}")
    print(f"status:  {resp.status_code}")
    print(f"reason:  {message}")
    print()
    print("response body (first 500 chars):")
    snippet = resp.text[:500].replace("\n", " ")
    print(f"  {snippet}")
    if len(resp.text) > 500:
        print(f"  ... ({len(resp.text) - 500} more chars)")


if __name__ == "__main__":
    asyncio.run(main())
