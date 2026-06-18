"""Persisted authenticated-session blob, stored as a 1Password secure note.

One note per program titled `autopoints:session:<program>`. The blob is
sensitive (cookies + tokens); never log it un-redacted — use `redacted()`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from autopoints.auth.op_client import CredentialBackend

SESSION_TITLE = "autopoints:session:{program}"


@dataclass
class SessionBlob:
    program: str
    captured_at: str
    expires_at_hint: str | None
    storage_state: dict[str, Any]
    additional_headers: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> SessionBlob:
        data = json.loads(raw)
        return cls(
            program=data["program"],
            captured_at=data["captured_at"],
            expires_at_hint=data.get("expires_at_hint"),
            storage_state=data.get("storage_state", {}),
            additional_headers=data.get("additional_headers", {}),
        )


def redacted(blob: SessionBlob) -> dict[str, Any]:
    return {
        "program": blob.program,
        "captured_at": blob.captured_at,
        "expires_at_hint": blob.expires_at_hint,
        "storage_state": "<redacted>",
        "additional_headers": "<redacted>",
    }


class SessionStore:
    def __init__(self, backend: CredentialBackend) -> None:
        self._backend = backend

    def load(self, program: str) -> SessionBlob | None:
        raw = self._backend.read_note(SESSION_TITLE.format(program=program))
        if not raw:
            return None
        try:
            return SessionBlob.from_json(raw)
        except (json.JSONDecodeError, KeyError):
            return None

    def save(self, blob: SessionBlob) -> None:
        self._backend.write_note(SESSION_TITLE.format(program=blob.program), blob.to_json())
