from __future__ import annotations

import base64
import json
import sys
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from agentplane_mcp_wrapper.domain import PendingDeviceAuthorization, TokenState
from agentplane_mcp_wrapper.pkce import code_challenge, generate_code_verifier

DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
AUTH_CODE_GRANT = "authorization_code"
REFRESH_TOKEN_GRANT = "refresh_token"  # noqa: S105 - OAuth grant type, not a secret.
HTTP_ERROR_STATUS = 400
JWT_MIN_PARTS = 2

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentplane_mcp_wrapper.config import OidcConfig


class OidcLoginError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OidcProviderMetadata:
    issuer: str
    token_endpoint: str
    authorization_endpoint: str
    device_authorization_endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserAuthorizationRequest:
    url: str
    state: str
    code_verifier: str
    redirect_uri: str


class OidcDeviceCodeLogin:
    def __init__(  # noqa: PLR0913 - dependency injection keeps login flow testable.
        self,
        *,
        config: OidcConfig,
        timeout_seconds: int = 300,
        http_client: httpx.Client | None = None,
        message_sink: Callable[[str], None] | None = None,
        now: Callable[[], int] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._client = http_client or httpx.Client(timeout=30)
        self._message_sink = message_sink or _stderr_message_sink
        self._now = now or (lambda: int(time.time()))
        self._sleep = sleep or time.sleep

    def login(self) -> TokenState:
        pending = self.start()
        self._message_sink(format_device_login_message(pending))
        return self._poll_until_token(pending)

    def start(self) -> PendingDeviceAuthorization:
        metadata = discover_provider_metadata(self._client, self._config)
        if not metadata.device_authorization_endpoint:
            msg = "OIDC provider metadata does not contain device_authorization_endpoint."
            raise OidcLoginError(msg)
        device_payload = self._request_device_code(metadata.device_authorization_endpoint)
        return pending_device_authorization_from_response(
            device_payload,
            token_endpoint=metadata.token_endpoint,
            issuer=self._config.issuer,
            now=self._now(),
        )

    def poll_once(self, pending: PendingDeviceAuthorization) -> TokenState | None:
        response = self._client.post(
            pending.token_endpoint,
            data={
                "grant_type": DEVICE_CODE_GRANT,
                "device_code": pending.device_code,
                "client_id": self._config.client_id,
            },
        )
        if response.status_code < HTTP_ERROR_STATUS:
            return token_state_from_response(
                _json_or_error(response, "token"),
                issuer=pending.issuer,
                now=self._now(),
            )
        payload = _safe_json(response)
        error_code = str(payload.get("error") or "")
        if error_code in {"authorization_pending", "slow_down"}:
            return None
        description = payload.get("error_description") or error_code or response.text
        msg = f"OIDC device authorization failed: {description}"
        raise OidcLoginError(msg)

    def _request_device_code(self, endpoint: str) -> dict[str, Any]:
        response = self._client.post(
            endpoint,
            data={
                "client_id": self._config.client_id,
                "scope": " ".join(self._config.scopes),
                "audience": self._config.audience,
            },
        )
        return _json_or_error(response, "device authorization")

    def _poll_until_token(self, pending: PendingDeviceAuthorization) -> TokenState:
        interval = pending.interval
        deadline = self._now() + self._timeout_seconds
        while self._now() <= deadline:
            token = self.poll_once(pending)
            if token is not None:
                return token
            self._sleep(interval)
        msg = "OIDC device authorization timed out."
        raise OidcLoginError(msg)


class OidcBrowserPkceLogin:
    def __init__(  # noqa: PLR0913 - dependency injection keeps login flow testable.
        self,
        *,
        config: OidcConfig,
        timeout_seconds: int = 300,
        http_client: httpx.Client | None = None,
        message_sink: Callable[[str], None] | None = None,
        browser_open: Callable[[str], object] | None = None,
        code_receiver: Callable[[BrowserAuthorizationRequest], str] | None = None,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._client = http_client or httpx.Client(timeout=30)
        self._message_sink = message_sink or _stderr_message_sink
        self._browser_open = browser_open or webbrowser.open
        self._code_receiver = code_receiver
        self._now = now or (lambda: int(time.time()))

    def login(self) -> TokenState:
        metadata = discover_provider_metadata(self._client, self._config)
        auth_request = build_browser_authorization_request(
            config=self._config,
            authorization_endpoint=metadata.authorization_endpoint,
        )
        self._message_sink(f"Opening browser for OIDC login: {auth_request.url}")
        self._browser_open(auth_request.url)
        code = (
            self._code_receiver(auth_request)
            if self._code_receiver is not None
            else wait_for_browser_callback(
                host=self._config.redirect_host,
                port=self._config.redirect_port,
                expected_state=auth_request.state,
                timeout_seconds=self._timeout_seconds,
            )
        )
        response = self._client.post(
            metadata.token_endpoint,
            data={
                "grant_type": AUTH_CODE_GRANT,
                "code": code,
                "redirect_uri": auth_request.redirect_uri,
                "client_id": self._config.client_id,
                "code_verifier": auth_request.code_verifier,
            },
        )
        return token_state_from_response(
            _json_or_error(response, "token"),
            issuer=self._config.issuer,
            now=self._now(),
        )


def build_browser_authorization_request(
    *,
    config: OidcConfig,
    authorization_endpoint: str,
    state: str | None = None,
    code_verifier: str | None = None,
) -> BrowserAuthorizationRequest:
    resolved_state = state or generate_code_verifier()[:43]
    resolved_verifier = code_verifier or generate_code_verifier()
    redirect_uri = f"http://{config.redirect_host}:{config.redirect_port}/callback"
    query = urlencode(
        {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(config.scopes),
            "state": resolved_state,
            "code_challenge": code_challenge(resolved_verifier),
            "code_challenge_method": "S256",
            "audience": config.audience,
        }
    )
    return BrowserAuthorizationRequest(
        url=f"{authorization_endpoint}?{query}",
        state=resolved_state,
        code_verifier=resolved_verifier,
        redirect_uri=redirect_uri,
    )


def wait_for_browser_callback(
    *,
    host: str,
    port: int,
    expected_state: str,
    timeout_seconds: int,
) -> str:
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]
            code = params.get("code", [""])[0]
            error = params.get("error", [""])[0]
            if error:
                result["error"] = error
                self._send_text(400, "OIDC login failed. You can close this tab.")
                return
            if state != expected_state:
                result["error"] = "state_mismatch"
                self._send_text(400, "OIDC state mismatch. You can close this tab.")
                return
            if not code:
                result["error"] = "missing_code"
                self._send_text(400, "OIDC code is missing. You can close this tab.")
                return
            result["code"] = code
            self._send_text(200, "OIDC login complete. You can close this tab.")

        def _send_text(self, status: int, message: str) -> None:
            body = message.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer((host, port), CallbackHandler)
    server.timeout = timeout_seconds
    try:
        server.handle_request()
    finally:
        server.server_close()
    if "code" in result:
        return result["code"]
    error = result.get("error", "timeout")
    msg = f"OIDC browser login failed: {error}."
    raise OidcLoginError(msg)


def discover_provider_metadata(
    http_client: httpx.Client,
    config: OidcConfig,
) -> OidcProviderMetadata:
    response = http_client.get(config.server_metadata_url)
    payload = _json_or_error(response, "provider metadata")
    metadata = OidcProviderMetadata(
        issuer=str(payload.get("issuer") or ""),
        token_endpoint=str(payload.get("token_endpoint") or ""),
        authorization_endpoint=str(payload.get("authorization_endpoint") or ""),
        device_authorization_endpoint=_optional_str(
            payload.get("device_authorization_endpoint")
        ),
    )
    missing = [
        field
        for field, value in (
            ("issuer", metadata.issuer),
            ("token_endpoint", metadata.token_endpoint),
            ("authorization_endpoint", metadata.authorization_endpoint),
        )
        if not value
    ]
    if missing:
        msg = f"OIDC provider metadata is missing required field(s): {', '.join(missing)}."
        raise OidcLoginError(msg)
    return metadata


def token_state_from_response(
    payload: dict[str, Any],
    *,
    issuer: str,
    now: int | None = None,
) -> TokenState:
    access_token = _required_str(payload, "access_token")
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in <= 0:
        msg = "OIDC token response is missing positive expires_in."
        raise OidcLoginError(msg)
    scope = tuple(str(payload.get("scope") or "").split())
    return TokenState(
        access_token=access_token,
        refresh_token=_optional_str(payload.get("refresh_token")),
        expires_at=(int(time.time()) if now is None else now) + expires_in,
        token_type=str(payload.get("token_type") or "Bearer"),
        scope=scope,
        subject=_subject_from_token_payload(payload),
        issuer=issuer,
    )


def pending_device_authorization_from_response(
    payload: dict[str, Any],
    *,
    token_endpoint: str,
    issuer: str,
    now: int | None = None,
) -> PendingDeviceAuthorization:
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in <= 0:
        msg = "OIDC device authorization response is missing positive expires_in."
        raise OidcLoginError(msg)
    return PendingDeviceAuthorization(
        device_code=_required_str(payload, "device_code"),
        user_code=_required_str(payload, "user_code"),
        verification_uri=_optional_str(payload.get("verification_uri")),
        verification_uri_complete=_optional_str(payload.get("verification_uri_complete")),
        token_endpoint=token_endpoint,
        issuer=issuer,
        expires_at=(int(time.time()) if now is None else now) + expires_in,
        interval=float(payload.get("interval") or 5),
    )


def refresh_token_state(
    *,
    config: OidcConfig,
    refresh_token: str,
    http_client: httpx.Client | None = None,
    now: int | None = None,
) -> TokenState:
    client = http_client or httpx.Client(timeout=30)
    metadata = discover_provider_metadata(client, config)
    response = client.post(
        metadata.token_endpoint,
        data={
            "grant_type": REFRESH_TOKEN_GRANT,
            "refresh_token": refresh_token,
            "client_id": config.client_id,
        },
    )
    return token_state_from_response(
        _json_or_error(response, "refresh token"),
        issuer=config.issuer,
        now=now,
    )


def _subject_from_token_payload(payload: dict[str, Any]) -> str | None:
    id_token = _optional_str(payload.get("id_token"))
    if id_token:
        claims = _decode_unsigned_jwt_payload(id_token)
        if claims:
            subject = claims.get("preferred_username") or claims.get("sub")
            return _optional_str(subject)
    return None


def _decode_unsigned_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < JWT_MIN_PARTS:
        return None
    segment = parts[1]
    padded = segment + ("=" * (-len(segment) % 4))
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def format_device_login_message(pending: PendingDeviceAuthorization) -> str:
    if pending.verification_uri_complete:
        return f"Open {pending.verification_uri_complete} and confirm code {pending.user_code}."
    if pending.verification_uri:
        return f"Open {pending.verification_uri} and enter code {pending.user_code}."
    return f"Enter device code {pending.user_code} in your identity provider."


def _json_or_error(response: httpx.Response, operation: str) -> dict[str, Any]:
    if response.status_code >= HTTP_ERROR_STATUS:
        payload = _safe_json(response)
        detail = payload.get("error_description") or payload.get("error") or response.text
        msg = f"OIDC {operation} request failed: {detail}"
        raise OidcLoginError(msg)
    payload = _safe_json(response)
    if not isinstance(payload, dict):
        msg = f"OIDC {operation} response must be a JSON object."
        raise OidcLoginError(msg)
    return payload


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        msg = "OIDC response is not valid JSON."
        raise OidcLoginError(msg) from exc
    if not isinstance(payload, dict):
        msg = "OIDC response JSON must be an object."
        raise OidcLoginError(msg)
    return payload


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = _optional_str(payload.get(field))
    if value is None:
        msg = f"OIDC response is missing required field: {field}."
        raise OidcLoginError(msg)
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _stderr_message_sink(message: str) -> None:
    print(message, file=sys.stderr)
