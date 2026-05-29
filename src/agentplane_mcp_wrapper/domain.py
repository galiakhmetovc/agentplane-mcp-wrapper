from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenState:
    access_token: str
    expires_at: int
    refresh_token: str | None = None
    token_type: str = "Bearer"  # noqa: S105 - OAuth token type, not a secret.
    scope: tuple[str, ...] = ()
    subject: str | None = None
    issuer: str | None = None

    def is_valid(self, *, now: int | None = None, skew_seconds: int = 30) -> bool:
        checked_at = int(time.time()) if now is None else now
        return self.expires_at > checked_at + skew_seconds


@dataclass(frozen=True, slots=True)
class PendingDeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str | None
    verification_uri_complete: str | None
    token_endpoint: str
    issuer: str
    expires_at: int
    interval: float = 5

    def is_valid(self, *, now: int | None = None, skew_seconds: int = 5) -> bool:
        checked_at = int(time.time()) if now is None else now
        return self.expires_at > checked_at + skew_seconds
