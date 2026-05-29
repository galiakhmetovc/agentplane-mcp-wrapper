from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast


@dataclass(frozen=True, slots=True)
class OidcConfig:
    issuer: str
    server_metadata_url: str
    client_id: str
    audience: str
    scopes: tuple[str, ...]
    redirect_host: str = "127.0.0.1"
    redirect_port: int = 8599


@dataclass(frozen=True, slots=True)
class LocalConfig:
    gateway_url: str
    client_name: str = "agentplane-mcp-wrapper"
    client_type: str = "local-wrapper"
    token_cache_path: Path = Path("~/.agentplane/mcp-wrapper-token.json")
    auto_device_login: bool = True
    login_flow: str = "device_code"
    login_timeout_seconds: int = 300
    request_timeout_seconds: float = 30.0
    oidc: OidcConfig | None = None


@dataclass(frozen=True, slots=True)
class WrapperConfig:
    mcp_local: LocalConfig


def load_config(path: str | Path) -> WrapperConfig:
    config_path = Path(path).expanduser()
    with config_path.open("rb") as file:
        values = tomllib.load(file)
    return config_from_mapping(values)


def config_from_mapping(values: Mapping[str, object]) -> WrapperConfig:
    local_values = _table(values, "mcp_local")
    oidc_values = _table(local_values, "oidc", label="mcp_local.oidc")
    oidc = OidcConfig(
        issuer=_required_text(oidc_values, "issuer", label="mcp_local.oidc.issuer"),
        server_metadata_url=_required_text(
            oidc_values,
            "server_metadata_url",
            label="mcp_local.oidc.server_metadata_url",
        ),
        client_id=_required_text(oidc_values, "client_id", label="mcp_local.oidc.client_id"),
        audience=_required_text(oidc_values, "audience", label="mcp_local.oidc.audience"),
        scopes=tuple(
            _string_list(oidc_values.get("scopes"), label="mcp_local.oidc.scopes")
        ),
        redirect_host=_text(oidc_values, "redirect_host", "127.0.0.1"),
        redirect_port=_int(oidc_values.get("redirect_port"), default=8599),
    )
    local = LocalConfig(
        gateway_url=_required_text(local_values, "gateway_url", label="mcp_local.gateway_url"),
        client_name=_text(local_values, "client_name", "agentplane-mcp-wrapper"),
        client_type=_text(local_values, "client_type", "local-wrapper"),
        token_cache_path=Path(
            _text(local_values, "token_cache_path", "~/.agentplane/mcp-wrapper-token.json")
        ).expanduser(),
        auto_device_login=_bool(local_values.get("auto_device_login"), default=True),
        login_flow=_text(local_values, "login_flow", "device_code"),
        login_timeout_seconds=_int(local_values.get("login_timeout_seconds"), default=300),
        request_timeout_seconds=float(
            _int(local_values.get("request_timeout_seconds"), default=30)
        ),
        oidc=oidc,
    )
    validate_config(WrapperConfig(mcp_local=local))
    return WrapperConfig(mcp_local=local)


def validate_config(config: WrapperConfig) -> None:
    local = config.mcp_local
    if not local.gateway_url.startswith(("https://", "http://")):
        msg = "[mcp_local].gateway_url must be an HTTP(S) URL."
        raise ValueError(msg)
    if local.login_flow not in {"device_code", "browser_pkce"}:
        msg = "[mcp_local].login_flow must be device_code or browser_pkce."
        raise ValueError(msg)
    if local.login_timeout_seconds <= 0:
        msg = "[mcp_local].login_timeout_seconds must be positive."
        raise ValueError(msg)
    if local.request_timeout_seconds <= 0:
        msg = "[mcp_local].request_timeout_seconds must be positive."
        raise ValueError(msg)
    if local.oidc is None:
        msg = "[mcp_local.oidc] is required."
        raise ValueError(msg)
    oidc = local.oidc
    if not oidc.issuer.startswith(("https://", "http://")):
        msg = "[mcp_local.oidc].issuer must be an HTTP(S) URL."
        raise ValueError(msg)
    if not oidc.server_metadata_url.startswith(("https://", "http://")):
        msg = "[mcp_local.oidc].server_metadata_url must be an HTTP(S) URL."
        raise ValueError(msg)
    if not oidc.scopes:
        msg = "[mcp_local.oidc].scopes must not be empty."
        raise ValueError(msg)


def _table(
    values: Mapping[str, object],
    key: str,
    *,
    label: str | None = None,
) -> Mapping[str, object]:
    value = values.get(key)
    if not isinstance(value, Mapping):
        msg = f"[{label or key}] must be a TOML table."
        raise TypeError(msg)
    return cast("Mapping[str, object]", value)


def _required_text(values: Mapping[str, object], key: str, *, label: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{label} is required."
        raise ValueError(msg)
    return value.strip()


def _text(values: Mapping[str, object], key: str, default: str) -> str:
    value = values.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _int(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        msg = "integer value cannot be boolean."
        raise TypeError(msg)
    return int(value)


def _bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        msg = "boolean value expected."
        raise TypeError(msg)
    return value


def _string_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        msg = f"{label} must be a non-empty string array."
        raise ValueError(msg)
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(result) != len(value):
        msg = f"{label} must contain only non-empty strings."
        raise ValueError(msg)
    return result
