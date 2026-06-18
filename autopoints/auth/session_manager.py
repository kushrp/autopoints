"""Session lifecycle: read from the store, cache in-process, refresh on expiry.

Runtime contract for callers: on a 401/403/expired search response, call
invalidate(program), then refresh(program) once, then retry the search once.
A second failure degrades to chart-floor (the provider's job), never a loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from autopoints.auth.session_store import SessionBlob, SessionStore

LoginFn = Callable[[str], SessionBlob]


@dataclass
class Session:
    blob: SessionBlob

    def cookies(self) -> dict[str, str]:
        jar: dict[str, str] = {}
        for cookie in self.blob.storage_state.get("cookies", []):
            name, value = cookie.get("name"), cookie.get("value")
            if name is not None and value is not None:
                jar[str(name)] = str(value)
        return jar

    def headers(self) -> dict[str, str]:
        return dict(self.blob.additional_headers)


class SessionManager:
    def __init__(self, store: SessionStore, login_fn: LoginFn) -> None:
        self._store = store
        self._login = login_fn
        self._cache: dict[str, Session] = {}

    def get(self, program: str) -> Session | None:
        cached = self._cache.get(program)
        if cached is not None:
            return cached
        blob = self._store.load(program)
        if blob is None:
            return None
        session = Session(blob)
        self._cache[program] = session
        return session

    def invalidate(self, program: str) -> None:
        self._cache.pop(program, None)

    def refresh(self, program: str) -> Session:
        blob = self._login(program)
        self._store.save(blob)
        session = Session(blob)
        self._cache[program] = session
        return session
