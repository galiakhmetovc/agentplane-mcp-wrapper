from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentplane_mcp_wrapper.gateway_client import LoginRequired, TokenProvider
from agentplane_mcp_wrapper.oidc import (
    OidcDeviceCodeLogin,
    OidcLoginError,
    format_device_login_message,
    refresh_token_state,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from agentplane_mcp_wrapper.config import OidcConfig
    from agentplane_mcp_wrapper.domain import PendingDeviceAuthorization, TokenState
    from agentplane_mcp_wrapper.token_cache import (
        FilePendingDeviceCodeCache,
        FileTokenCache,
    )


@dataclass(frozen=True, slots=True)
class AutoLoginTokenProvider(TokenProvider):
    token_cache: FileTokenCache
    pending_cache: FilePendingDeviceCodeCache
    oidc: OidcConfig
    auto_device_login: bool = True
    http_client: httpx.Client | None = None
    now: Callable[[], int] | None = None

    def access_token(self) -> str | None:
        now = self._now()
        state = self.token_cache.load()
        if state is not None and state.is_valid(now=now):
            return state.access_token
        if state is not None and state.refresh_token:
            refreshed = self._try_refresh_token(state.refresh_token, now=now)
            if refreshed is not None:
                self.token_cache.save(refreshed)
                return refreshed.access_token
            self.token_cache.clear()
        if not self.auto_device_login:
            return None
        return self._start_or_resume_device_login(now=now)

    def _try_refresh_token(self, refresh_token: str, *, now: int) -> TokenState | None:
        try:
            return refresh_token_state(
                config=self.oidc,
                refresh_token=refresh_token,
                http_client=self.http_client,
                now=now,
            )
        except OidcLoginError:
            return None

    def _start_or_resume_device_login(self, *, now: int) -> str:
        login = OidcDeviceCodeLogin(
            config=self.oidc,
            http_client=self.http_client,
            now=lambda: now,
            sleep=lambda _: None,
        )
        pending = self.pending_cache.load(now=now)
        if pending is not None:
            token = login.poll_once(pending)
            if token is not None:
                self.token_cache.save(token)
                self.pending_cache.clear()
                return token.access_token
            raise LoginRequired(_device_login_required_message(pending))

        pending = login.start()
        self.pending_cache.save(pending)
        raise LoginRequired(_device_login_required_message(pending))

    def _now(self) -> int:
        return int(time.time()) if self.now is None else self.now()


def _device_login_required_message(pending: PendingDeviceAuthorization) -> str:
    return (
        "Login required. "
        f"{format_device_login_message(pending)} "
        "After login, repeat this MCP tool call."
    )
