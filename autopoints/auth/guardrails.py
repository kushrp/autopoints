"""R7 anti-ban guardrails, enforced in code rather than policy comments.

The risk: the airline notices an account is automated and bans it. These rules
minimize that: a slow jittered cadence, a daily cap, single concurrency, a URL
allowlist, a read-only method gate, and an auto-freeze on any hostile response.
Clock and jitter are injected so the rules are deterministically testable.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

_DAY_SECONDS = 86_400
_CHALLENGE_MARKERS = ("unusual activity", "verify you are human", "access denied", "captcha")


class GuardError(Exception): ...


class RateLimited(GuardError): ...


class DailyCapExceeded(GuardError): ...


class Frozen(GuardError): ...


class DisallowedRequest(GuardError): ...


@dataclass
class AntiBanGuard:
    program: str
    allowed_url_prefixes: tuple[str, ...]
    min_interval_s: float = 60.0
    jitter_s: float = 10.0
    daily_cap: int = 100
    now: Callable[[], float] = time.time
    rng: Callable[[], float] = random.random

    _last_call: float | None = field(default=None, init=False)
    _calls: list[float] = field(default_factory=list, init=False)
    _in_flight: bool = field(default=False, init=False)
    _frozen_until: float = field(default=0.0, init=False)

    def check_url(self, url: str) -> None:
        if not any(url.startswith(prefix) for prefix in self.allowed_url_prefixes):
            raise DisallowedRequest(f"{self.program}: URL not allowlisted: {url}")

    def check_method(self, method: str) -> None:
        if method.upper() not in {"GET", "POST"}:
            raise DisallowedRequest(f"{self.program}: method not allowed: {method}")

    def acquire(self) -> None:
        now = self.now()
        if now < self._frozen_until:
            raise Frozen(f"{self.program}: frozen until {self._frozen_until:.0f}")
        if self._in_flight:
            raise RateLimited(f"{self.program}: a request is already in flight")
        self._calls = [t for t in self._calls if now - t < _DAY_SECONDS]
        if len(self._calls) >= self.daily_cap:
            raise DailyCapExceeded(f"{self.program}: daily cap {self.daily_cap} reached")
        if self._last_call is not None:
            wait = self.min_interval_s + self.jitter_s * self.rng()
            if now - self._last_call < wait:
                raise RateLimited(
                    f"{self.program}: {wait - (now - self._last_call):.0f}s until allowed"
                )
        self._last_call = now
        self._calls.append(now)
        self._in_flight = True

    def release(self) -> None:
        self._in_flight = False

    def note_response(self, status: int, body: str = "") -> None:
        hostile = status in (429, 403) or any(m in body.lower() for m in _CHALLENGE_MARKERS)
        if hostile:
            self._frozen_until = self.now() + _DAY_SECONDS

    @property
    def is_frozen(self) -> bool:
        return self.now() < self._frozen_until
