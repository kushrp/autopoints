"""Preflight diagnostic: reports which live-path prerequisites are present.

Run before the first authenticated login so missing pieces surface as a
checklist rather than a runtime failure mid-flow.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass
class PreflightResult:
    op_cli: bool
    connect: bool
    browserbase: bool

    @property
    def credentials_ready(self) -> bool:
        return self.op_cli or self.connect

    @property
    def ready(self) -> bool:
        return self.credentials_ready and self.browserbase

    def report(self) -> str:
        def mark(ok: bool) -> str:
            return "OK" if ok else "MISSING"

        lines = [
            f"[{mark(self.op_cli)}] 1Password CLI (`op` on PATH) — laptop credential source",
            f"[{mark(self.connect)}] 1Password Connect (OP_CONNECT_HOST + OP_CONNECT_TOKEN) — NAS source",
            f"[{mark(self.browserbase)}] Browserbase (BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID)",
        ]
        if not self.credentials_ready:
            lines.append(
                "-> Need at least one credential source. See docs/ops/1password-connect-nas-setup.md."
            )
        if not self.browserbase:
            lines.append("-> Set Browserbase env vars to run the login flow.")
        if self.ready:
            lines.append("-> Ready for authenticated login.")
        return "\n".join(lines)


def preflight() -> PreflightResult:
    return PreflightResult(
        op_cli=shutil.which("op") is not None,
        connect=bool(os.environ.get("OP_CONNECT_HOST") and os.environ.get("OP_CONNECT_TOKEN")),
        browserbase=bool(
            os.environ.get("BROWSERBASE_API_KEY") and os.environ.get("BROWSERBASE_PROJECT_ID")
        ),
    )
