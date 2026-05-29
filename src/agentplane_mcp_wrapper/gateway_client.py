from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class LoginRequired(RuntimeError):  # noqa: N818 - domain phrase reads better at call sites.
    pass


class RemoteMcpGatewayError(RuntimeError):
    def __init__(self, *, operation: str, gateway_url: str, cause: BaseException) -> None:
        super().__init__(
            f"Unable to {operation} through MCP Gateway {gateway_url}: "
            f"{_format_exception(cause)}"
        )


class TokenProvider(Protocol):
    def access_token(self) -> str | None: ...


class RemoteMcpSession(Protocol):
    async def list_tools(self) -> object: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> object: ...


SessionFactory = Callable[..., AbstractAsyncContextManager[RemoteMcpSession]]


@dataclass(frozen=True, slots=True)
class StaticTokenProvider:
    token: str | None

    def access_token(self) -> str | None:
        return self.token


class RemoteMcpGatewayClient:
    def __init__(
        self,
        *,
        gateway_url: str,
        token_provider: TokenProvider,
        timeout_seconds: float = 30.0,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._gateway_url = gateway_url
        self._token_provider = token_provider
        self._timeout_seconds = timeout_seconds
        self._session_factory = session_factory or mcp_session

    async def list_tools(self) -> object:
        try:
            async with self._open_session() as session:
                return await session.list_tools()
        except LoginRequired:
            raise
        except Exception as exc:
            operation = "list tools"
            raise self._gateway_error(operation, exc) from exc

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        node_id: str | None = None,
    ) -> object:
        remote_arguments = dict(arguments)
        if node_id:
            remote_arguments["node_id"] = node_id
        return await self._call_tool(name, remote_arguments)

    async def find_targets(self, payload: dict[str, Any]) -> object:
        return await self._call_tool("find_targets", dict(payload))

    async def run_remote_tool(self, payload: dict[str, Any]) -> object:
        return await self._call_tool("run_remote_tool", dict(payload))

    async def get_remote_run(self, payload: dict[str, Any]) -> object:
        return await self._call_tool("get_remote_run", dict(payload))

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> object:
        try:
            async with self._open_session() as session:
                return await session.call_tool(name, arguments)
        except LoginRequired:
            raise
        except Exception as exc:
            operation = f"call tool {name}"
            raise self._gateway_error(operation, exc) from exc

    def _open_session(self) -> AbstractAsyncContextManager[RemoteMcpSession]:
        token = self._token_provider.access_token()
        if not token:
            msg = "Login required. Run: agentplane-mcp-wrapper login --config <config>"
            raise LoginRequired(msg)
        return self._session_factory(
            url=self._gateway_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout_seconds=self._timeout_seconds,
        )

    def _gateway_error(self, operation: str, exc: BaseException) -> RemoteMcpGatewayError:
        return RemoteMcpGatewayError(
            operation=operation,
            gateway_url=self._gateway_url,
            cause=exc,
        )


def _format_exception(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        children = "; ".join(_format_exception(item) for item in exc.exceptions)
        return f"{type(exc).__name__}: {exc.message} ({children})"
    message = str(exc)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


@asynccontextmanager
async def mcp_session(
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> AsyncIterator[ClientSession]:
    async with (
        streamablehttp_client(
            url,
            headers=headers,
            timeout=timeout_seconds,
        ) as (read_stream, write_stream, _get_session_id),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session
