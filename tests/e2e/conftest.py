"""Shared fixtures for browser-driven end-to-end tests."""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
PY = ROOT / ".venv" / "bin" / "python"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float = 20.0) -> None:
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


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """Boot uvicorn on a free port with an isolated cache; yield the base URL."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    tmp = Path(tempfile.mkdtemp(prefix="autopoints-e2e-browser-"))
    env = {**os.environ, "AUTOPOINTS_CACHE_PATH": str(tmp / "cache.db")}

    proc = subprocess.Popen(
        [
            str(PY), "-m", "uvicorn", "autopoints.api.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
    )
    try:
        _wait_for_server(f"{base}/api/health")
        # `/` redirects to `/onboard` on a fresh install. The browser test
        # exercises the search SPA directly, so drop the onboard sentinel
        # before the test navigates. Isolated AUTOPOINTS_CACHE_PATH means
        # this doesn't leak into other runs.
        urlopen(Request(f"{base}/api/onboard/complete", method="POST"), timeout=5).read()
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
