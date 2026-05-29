from __future__ import annotations

import json
from dataclasses import asdict
from os import O_CREAT, O_TRUNC, O_WRONLY, fdopen
from os import open as os_open
from pathlib import Path

from agentplane_mcp_wrapper.domain import PendingDeviceAuthorization, TokenState


class FileTokenCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def load(self) -> TokenState | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return TokenState(
            access_token=str(payload["access_token"]),
            expires_at=int(payload["expires_at"]),
            refresh_token=_optional_text(payload.get("refresh_token")),
            token_type=str(payload.get("token_type") or "Bearer"),
            scope=tuple(str(item) for item in payload.get("scope", ())),
            subject=_optional_text(payload.get("subject")),
            issuer=_optional_text(payload.get("issuer")),
        )

    def load_valid(self, *, now: int | None = None) -> TokenState | None:
        state = self.load()
        if state is None or not state.is_valid(now=now):
            return None
        return state

    def save(self, state: TokenState) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        payload = asdict(state)
        payload["scope"] = list(state.scope)
        data = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
        fd = os_open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC, 0o600)
        try:
            with fdopen(fd, "wb") as token_file:
                token_file.write(data)
                token_file.write(b"\n")
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        tmp_path.replace(self.path)
        self.path.chmod(0o600)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class FilePendingDeviceCodeCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    @classmethod
    def for_token_cache(cls, token_cache_path: str | Path) -> FilePendingDeviceCodeCache:
        token_path = Path(token_cache_path).expanduser()
        return cls(token_path.with_name(f".{token_path.name}.device-login.json"))

    def load(self, *, now: int | None = None) -> PendingDeviceAuthorization | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        pending = PendingDeviceAuthorization(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_uri=_optional_text(payload.get("verification_uri")),
            verification_uri_complete=_optional_text(payload.get("verification_uri_complete")),
            token_endpoint=str(payload["token_endpoint"]),
            issuer=str(payload["issuer"]),
            expires_at=int(payload["expires_at"]),
            interval=float(payload.get("interval") or 5),
        )
        if pending.is_valid(now=now):
            return pending
        self.clear()
        return None

    def save(self, pending: PendingDeviceAuthorization) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        data = json.dumps(asdict(pending), sort_keys=True, indent=2).encode("utf-8")
        fd = os_open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC, 0o600)
        try:
            with fdopen(fd, "wb") as token_file:
                token_file.write(data)
                token_file.write(b"\n")
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        tmp_path.replace(self.path)
        self.path.chmod(0o600)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
