#!/usr/bin/env python3
"""End-to-end smoke test.

Boots the FastAPI server on a free port, exercises every HTTP endpoint and
CLI subcommand against demo data, and reports PASS/FAIL with timings.

Usage:
    scripts/e2e.py             # full suite
    scripts/e2e.py --api-only  # skip CLI steps
    scripts/e2e.py --keep      # leave the server running on exit
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import json

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
AUTOPOINTS = ROOT / ".venv" / "bin" / "autopoints"

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class StepFailed(Exception):
    pass


def step(name: str):
    def deco(fn):
        def wrapped(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                dt = (time.perf_counter() - t0) * 1000
                print(f"  {GREEN}PASS{RESET}  {name} {DIM}({dt:.0f}ms){RESET}")
                return result
            except Exception as e:
                dt = (time.perf_counter() - t0) * 1000
                print(f"  {RED}FAIL{RESET}  {name} {DIM}({dt:.0f}ms){RESET}")
                print(f"        {RED}{e}{RESET}")
                raise StepFailed(name) from e
        return wrapped
    return deco


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return
        except (URLError, HTTPError, ConnectionError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"server at {url} didn't come up within {timeout}s")


def http_get(url: str) -> tuple[int, dict | str]:
    try:
        with urlopen(url, timeout=10) as r:
            body = r.read().decode()
            ctype = r.headers.get("content-type", "")
            return r.status, json.loads(body) if "json" in ctype else body
    except HTTPError as e:
        return e.code, e.read().decode()


def http_post(url: str, body: dict) -> tuple[int, dict]:
    req = Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except HTTPError as e:
        return e.code, json.loads(e.read().decode())


def http_delete(url: str) -> int:
    req = Request(url, method="DELETE")
    try:
        with urlopen(req, timeout=10) as r:
            return r.status
    except HTTPError as e:
        return e.code


# ---- assertions ----

def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def assert_in(needle, haystack, msg=""):
    if needle not in haystack:
        raise AssertionError(f"{msg}: {needle!r} not in {haystack!r}")


def assert_truthy(value, msg=""):
    if not value:
        raise AssertionError(f"{msg}: got falsy {value!r}")


# ---- API steps ----

class API:
    def __init__(self, base_url: str):
        self.base = base_url

    @step("GET / serves index HTML")
    def index_html(self):
        code, body = http_get(self.base + "/")
        assert_eq(code, 200, "status")
        assert_in("<form id=\"search-form\"", body, "form rendered")
        assert_in("/static/app.js", body, "app.js linked")
        assert_in("programs-data", body, "programs bootstrap data injected")

    @step("GET /static/app.js + styles.css")
    def static_assets(self):
        for path in ("/static/app.js", "/static/styles.css"):
            code, body = http_get(self.base + path)
            assert_eq(code, 200, path)
            assert_truthy(len(body) > 1000, f"{path} non-trivial size")

    @step("GET /api/health")
    def health(self):
        code, body = http_get(self.base + "/api/health")
        assert_eq(code, 200, "status")
        assert_eq(body["status"], "ok", "status field")
        assert_truthy(body["version"], "version present")

    @step("GET /api/programs returns valuations + ratios + charts")
    def programs(self):
        code, body = http_get(self.base + "/api/programs")
        assert_eq(code, 200, "status")
        assert_eq(body["supported_charts"], ["AC", "BA", "VS"], "charts")
        assert_in("UR", body["transfer_ratios"], "UR in ratios")
        assert_in("MR", body["transfer_ratios"], "MR in ratios")
        assert_truthy(body["valuations"]["AC"] > 0, "AC valuation positive")
        assert_truthy(body["cpp_thresholds"]["great"] >= body["cpp_thresholds"]["good"], "thresholds ordered")

    @step("POST /api/search returns ranked redemptions")
    def search(self):
        code, body = http_post(
            self.base + "/api/search",
            {
                "origin": "JFK", "destination": "PHX",
                "depart_date": "2026-06-15", "window_days": 2,
                "cabin": "economy", "passengers": 1,
                "demo": True, "live_aeroplan": False,
            },
        )
        assert_eq(code, 200, "status")
        assert_truthy(len(body["redemptions"]) > 0, "got redemptions")
        assert_eq(len(body["cheapest_cash_by_date"]), 5, "5 dates in window=2")
        cpps = [r["effective_cpp"] for r in body["redemptions"]]
        assert_eq(cpps, sorted(cpps, reverse=True), "sorted by CPP desc")
        for r in body["redemptions"]:
            assert_in(r["verdict"], ("great", "good", "ok", "bad"), "verdict valid")
            assert_in(r["transfer_program"], ("UR", "MR", "DIRECT"), "transfer valid")
            assert_in(r["points_program"], ("AC", "BA", "VS"), "program valid")

    @step("POST /api/search validates IATA codes")
    def search_validates(self):
        code, _ = http_post(
            self.base + "/api/search",
            {"origin": "ABCD", "destination": "PHX", "depart_date": "2026-06-15", "demo": True},
        )
        assert_eq(code, 422, "rejects 4-char origin")

    @step("Watchlist CRUD + run + diff cycle")
    def watchlist_cycle(self):
        # Create
        code, wl = http_post(
            self.base + "/api/watchlists",
            {
                "origin": "JFK", "destination": "LAX",
                "depart_date": "2026-07-01", "window_days": 1,
                "cabin": "economy", "passengers": 1,
                "threshold_cpp": 1.0, "label": "e2e-test",
            },
        )
        assert_eq(code, 200, "create status")
        wl_id = wl["id"]
        assert_eq(wl["label"], "e2e-test", "label")

        # List
        code, body = http_get(self.base + "/api/watchlists")
        assert_eq(code, 200, "list status")
        assert_truthy(any(w["id"] == wl_id for w in body), "new watchlist appears in list")

        # Run #1 — all hits should be NEW
        code, runs = http_post(self.base + "/api/watchlists/run?demo=true", {})
        assert_eq(code, 200, "run status")
        our_run = next(r for r in runs if r["watchlist"]["id"] == wl_id)
        assert_truthy(len(our_run["hits"]) > 0, "first run produced hits")
        assert_truthy(all(h["is_new"] for h in our_run["hits"]), "all first-run hits flagged new")

        # Run #2 — diff should mark them as not new
        code, runs = http_post(self.base + "/api/watchlists/run?demo=true", {})
        our_run = next(r for r in runs if r["watchlist"]["id"] == wl_id)
        assert_truthy(all(not h["is_new"] for h in our_run["hits"]), "second run marks hits not-new")

        # Delete
        assert_eq(http_delete(self.base + f"/api/watchlists/{wl_id}"), 200, "delete status")
        assert_eq(http_delete(self.base + f"/api/watchlists/{wl_id}"), 404, "second delete 404s")


# ---- CLI steps ----

class CLI:
    def __init__(self, env: dict):
        self.env = env

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(AUTOPOINTS), *args],
            capture_output=True, text=True, env=self.env, timeout=30,
        )

    @step("autopoints --help")
    def help(self):
        r = self._run("--help")
        assert_eq(r.returncode, 0, "exit code")
        assert_in("search", r.stdout, "search subcommand listed")
        assert_in("watchlist", r.stdout, "watchlist subcommand listed")

    @step("autopoints search JFK PHX --demo")
    def search(self):
        r = self._run("search", "JFK", "PHX", "2026-06-15", "--demo")
        assert_eq(r.returncode, 0, f"exit code (stderr: {r.stderr[-200:]})")
        assert_in("JFK", r.stdout, "route rendered")
        assert_in("cpp", r.stdout.lower(), "CPP column present")

    @step("autopoints watchlist add/list/remove cycle")
    def watchlist(self):
        r = self._run("watchlist", "add", "JFK", "LAX", "2026-08-01", "--threshold", "1.5", "--label", "e2e-cli")
        assert_eq(r.returncode, 0, f"add (stderr: {r.stderr[-200:]})")
        assert_in("added watchlist", r.stdout, "add confirmation")
        wl_id = r.stdout.split("watchlist ")[1].split(":")[0].strip()

        r = self._run("watchlist", "list")
        assert_eq(r.returncode, 0, "list")
        assert_in("e2e-cli", r.stdout, "label appears in list")

        r = self._run("watchlist", "run", "--demo")
        assert_eq(r.returncode, 0, f"run (stderr: {r.stderr[-200:]})")
        assert_in("hits", r.stdout, "run reports hits")

        r = self._run("watchlist", "remove", wl_id)
        assert_eq(r.returncode, 0, "remove")


# ---- main ----

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-only", action="store_true")
    ap.add_argument("--cli-only", action="store_true")
    ap.add_argument("--keep", action="store_true", help="leave server running on exit")
    args = ap.parse_args()

    port = free_port()
    base = f"http://127.0.0.1:{port}"

    # Isolated storage so the test doesn't trample real state.
    tmp = Path(tempfile.mkdtemp(prefix="autopoints-e2e-"))
    env = {**os.environ, "AUTOPOINTS_CACHE_PATH": str(tmp / "cache.db")}

    print(f"{BOLD}autopoints E2E smoke test{RESET}")
    print(f"  server: {base}")
    print(f"  state:  {tmp}")
    print()

    server = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "autopoints.api.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        cwd=str(ROOT),
    )

    failures: list[str] = []
    try:
        wait_for_server(f"{base}/api/health")

        if not args.cli_only:
            print(f"{BOLD}HTTP API{RESET}")
            api = API(base)
            for s in (api.index_html, api.static_assets, api.health,
                      api.programs, api.search, api.search_validates,
                      api.watchlist_cycle):
                try:
                    s()
                except StepFailed as e:
                    failures.append(str(e))
            print()

        if not args.api_only:
            print(f"{BOLD}CLI{RESET}")
            cli = CLI(env)
            for s in (cli.help, cli.search, cli.watchlist):
                try:
                    s()
                except StepFailed as e:
                    failures.append(str(e))
            print()
    finally:
        if not args.keep:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()

    if failures:
        print(f"{RED}{BOLD}{len(failures)} step(s) failed:{RESET}")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"{GREEN}{BOLD}All steps passed.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
