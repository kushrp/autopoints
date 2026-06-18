"""1Password access for credentials, TOTP, and the persisted session blob.

Auto-detects 1Password Connect (NAS, via OP_CONNECT_HOST + OP_CONNECT_TOKEN)
vs the local `op` CLI (laptop). The local backend is fully implemented and
unblocks the first login on a dev machine; the Connect backend is validated
during the NAS cutover (see docs/ops/1password-connect-nas-setup.md).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol


class AuthError(Exception):
    """Credential or session-store access failed."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


class CredentialBackend(Protocol):
    def get_field(self, item: str, field: str) -> str: ...
    def get_otp(self, item: str) -> str | None: ...
    def read_note(self, title: str) -> str | None: ...
    def write_note(self, title: str, body: str) -> None: ...


class LocalCliBackend:
    """1Password local CLI (`op`), for interactive devices."""

    def __init__(self, vault: str | None = None) -> None:
        if shutil.which("op") is None:
            raise AuthError(
                "1Password CLI `op` not found on PATH. See docs/ops/1password-connect-nas-setup.md."
            )
        self._vault = vault

    def _run(self, args: list[str]) -> str:
        cmd = ["op", *args]
        if self._vault:
            cmd += ["--vault", self._vault]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except FileNotFoundError as e:
            raise AuthError("`op` CLI not available") from e
        except subprocess.CalledProcessError as e:
            raise AuthError(f"op command failed: {(e.stderr or '').strip() or e}") from e
        return result.stdout.strip()

    def get_field(self, item: str, field: str) -> str:
        return self._run(["item", "get", item, "--fields", f"label={field}", "--reveal"])

    def get_otp(self, item: str) -> str | None:
        try:
            return self._run(["item", "get", item, "--otp"]) or None
        except AuthError:
            return None

    def read_note(self, title: str) -> str | None:
        try:
            raw = self._run(["item", "get", title, "--format", "json"])
        except AuthError:
            return None
        data = json.loads(raw)
        for field in data.get("fields", []):
            if field.get("id") == "notesPlain" or field.get("label") == "notesPlain":
                value = field.get("value")
                return str(value) if value is not None else None
        return None

    def write_note(self, title: str, body: str) -> None:
        assignment = f"notesPlain={body}"
        try:
            self._run(["item", "get", title])
        except AuthError:
            self._run(["item", "create", "--category", "Secure Note", "--title", title, assignment])
            return
        self._run(["item", "edit", title, assignment])


class ConnectBackend:
    """1Password Connect REST backend for the always-on NAS daemon.

    PROVISIONAL: endpoint shapes follow the documented Connect API; validate
    against a live Connect server during the NAS cutover.
    """

    def __init__(self, host: str, token: str, vault: str) -> None:
        import httpx

        self._vault = vault
        self._client = httpx.Client(
            base_url=host.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15.0,
        )

    def _item_id(self, title: str) -> str | None:
        resp = self._client.get(
            f"/v1/vaults/{self._vault}/items", params={"filter": f'title eq "{title}"'}
        )
        resp.raise_for_status()
        items = resp.json()
        return str(items[0]["id"]) if items else None

    def _full_item(self, title: str) -> dict[str, Any] | None:
        item_id = self._item_id(title)
        if item_id is None:
            return None
        resp = self._client.get(f"/v1/vaults/{self._vault}/items/{item_id}")
        resp.raise_for_status()
        return dict(resp.json())

    def get_field(self, item: str, field: str) -> str:
        full = self._full_item(item)
        if full is None:
            raise AuthError(f"Connect: item {item!r} not found")
        for f in full.get("fields", []):
            if f.get("label") == field or f.get("id") == field:
                return str(f.get("value", ""))
        raise AuthError(f"Connect: field {field!r} not on item {item!r}")

    def get_otp(self, item: str) -> str | None:
        full = self._full_item(item)
        if full is None:
            return None
        for f in full.get("fields", []):
            if f.get("type") == "OTP" and f.get("totp"):
                return str(f["totp"])
        return None

    def read_note(self, title: str) -> str | None:
        full = self._full_item(title)
        if full is None:
            return None
        for f in full.get("fields", []):
            if f.get("id") == "notesPlain":
                value = f.get("value")
                return str(value) if value is not None else None
        return None

    def write_note(self, title: str, body: str) -> None:
        field = {"id": "notesPlain", "type": "STRING", "purpose": "NOTES", "value": body}
        item_id = self._item_id(title)
        if item_id is None:
            payload = {
                "vault": {"id": self._vault},
                "title": title,
                "category": "SECURE_NOTE",
                "fields": [field],
            }
            self._client.post(
                f"/v1/vaults/{self._vault}/items", content=json.dumps(payload)
            ).raise_for_status()
            return
        self._client.patch(
            f"/v1/vaults/{self._vault}/items/{item_id}",
            content=json.dumps(
                [{"op": "replace", "path": "/fields/notesPlain/value", "value": body}]
            ),
        ).raise_for_status()


def make_backend(vault: str | None = None) -> CredentialBackend:
    """Connect when its env is present, else the local CLI."""
    host = os.environ.get("OP_CONNECT_HOST")
    token = os.environ.get("OP_CONNECT_TOKEN")
    if host and token:
        return ConnectBackend(host, token, vault or os.environ.get("OP_VAULT", "autopoints"))
    return LocalCliBackend(vault=vault or os.environ.get("OP_VAULT"))


class OnePasswordClient:
    """Domain-level credential access over whichever backend is configured."""

    def __init__(self, backend: CredentialBackend) -> None:
        self._backend = backend

    def credentials(self, item: str) -> Credentials:
        return Credentials(
            username=self._backend.get_field(item, "username"),
            password=self._backend.get_field(item, "password"),
        )

    def otp(self, item: str) -> str | None:
        return self._backend.get_otp(item)
