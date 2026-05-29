from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from agentplane_mcp_wrapper.auto_login import AutoLoginTokenProvider
from agentplane_mcp_wrapper.config import WrapperConfig, load_config
from agentplane_mcp_wrapper.gateway_client import RemoteMcpGatewayClient
from agentplane_mcp_wrapper.oidc import OidcBrowserPkceLogin, OidcDeviceCodeLogin
from agentplane_mcp_wrapper.server import build_local_mcp_server
from agentplane_mcp_wrapper.token_cache import FilePendingDeviceCodeCache, FileTokenCache

if TYPE_CHECKING:
    from agentplane_mcp_wrapper.domain import TokenState


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    command = args.command or "serve"
    try:
        config = _load_config_argument(args.config)
        handlers = {
            "serve": lambda: serve(config),
            "login": lambda: login(config, flow=args.flow),
            "logout": lambda: logout(config),
            "status": lambda: status(config),
        }
        handler = handlers.get(command)
        if handler is None:
            parser.error(f"unknown command: {command}")
            return 2
        return handler()
    except Exception as exc:  # noqa: BLE001 - CLI boundary.
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument("--config", help="Path to TOML config file.")

    parser = argparse.ArgumentParser(
        prog="agentplane-mcp-wrapper",
        parents=[config_parent],
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", parents=[config_parent], help="Run local MCP stdio server.")

    login_parser = subparsers.add_parser(
        "login",
        parents=[config_parent],
        help="Login through AgentPlane and cache a local access token.",
    )
    login_parser.add_argument(
        "--flow",
        choices=("device_code", "browser_pkce"),
        help="Override [mcp_local].login_flow for this login.",
    )

    subparsers.add_parser("logout", parents=[config_parent], help="Delete cached token.")
    subparsers.add_parser("status", parents=[config_parent], help="Show local login status.")
    return parser


def serve(config: WrapperConfig) -> int:
    local = config.mcp_local
    if local.oidc is None:
        msg = "[mcp_local.oidc] is required."
        raise ValueError(msg)
    cache = FileTokenCache(local.token_cache_path)
    gateway_client = RemoteMcpGatewayClient(
        gateway_url=local.gateway_url,
        token_provider=AutoLoginTokenProvider(
            token_cache=cache,
            pending_cache=FilePendingDeviceCodeCache.for_token_cache(local.token_cache_path),
            oidc=local.oidc,
            auto_device_login=local.auto_device_login,
        ),
        timeout_seconds=local.request_timeout_seconds,
    )
    server = build_local_mcp_server(gateway_client=gateway_client, name=local.client_name)
    server.run("stdio")
    return 0


def _load_config_argument(value: str | None) -> WrapperConfig:
    if not value:
        msg = "--config is required."
        raise ValueError(msg)
    return load_config(value)


def login(config: WrapperConfig, *, flow: str | None = None) -> int:
    local = config.mcp_local
    if local.oidc is None:
        msg = "[mcp_local.oidc] is required."
        raise ValueError(msg)
    resolved_flow = flow or local.login_flow
    if resolved_flow == "device_code":
        provider = OidcDeviceCodeLogin(
            config=local.oidc,
            timeout_seconds=local.login_timeout_seconds,
        )
    elif resolved_flow == "browser_pkce":
        provider = OidcBrowserPkceLogin(
            config=local.oidc,
            timeout_seconds=local.login_timeout_seconds,
        )
    else:
        msg = f"Unsupported login flow: {resolved_flow}"
        raise ValueError(msg)
    state = provider.login()
    FileTokenCache(local.token_cache_path).save(state)
    _print_token_status("Logged in", state)
    return 0


def logout(config: WrapperConfig) -> int:
    FileTokenCache(config.mcp_local.token_cache_path).clear()
    print("Logged out.", file=sys.stderr)
    return 0


def status(config: WrapperConfig) -> int:
    cache = FileTokenCache(config.mcp_local.token_cache_path)
    state = cache.load_valid()
    if state is None:
        print("Not logged in: token is missing or expired.", file=sys.stderr)
        return 1
    _print_token_status("Logged in", state)
    return 0


def _print_token_status(prefix: str, state: TokenState) -> None:
    subject = state.subject or "<unknown>"
    scopes = " ".join(state.scope) if state.scope else "-"
    print(
        f"{prefix}: subject={subject} expires_at={state.expires_at} scopes={scopes}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
