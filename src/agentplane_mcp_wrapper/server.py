from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from agentplane_mcp_wrapper.gateway_client import LoginRequired


class GatewayClient(Protocol):
    async def list_tools(self) -> object: ...

    async def find_targets(self, payload: dict[str, Any]) -> object: ...

    async def run_remote_tool(self, payload: dict[str, Any]) -> object: ...

    async def get_remote_run(self, payload: dict[str, Any]) -> object: ...


def build_local_mcp_server(
    *,
    gateway_client: GatewayClient,
    name: str = "agentplane-mcp-wrapper",
) -> FastMCP:
    server = FastMCP(
        name,
        instructions=(
            "This local MCP wrapper proxies tool discovery and execution to the "
            "central Agent Control Plane MCP Gateway. Use list_remote_tools to inspect "
            "available remote tools and target schema, then find_targets, "
            "run_remote_tool, and get_remote_run for execution."
        ),
    )

    @server.tool(
        name="list_remote_tools",
        description="Lists policy-filtered tools exposed by the central MCP Gateway.",
        structured_output=True,
    )
    async def list_remote_tools() -> dict[str, Any]:
        try:
            return _to_json_object(await gateway_client.list_tools())
        except LoginRequired as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="find_targets",
        description="Resolve remote execution targets through the central MCP Gateway.",
        structured_output=True,
    )
    async def find_targets(
        filter: dict[str, Any],  # noqa: A002 - public MCP schema field is named "filter".
        limit: int = 500,
        dry_run: bool = False,  # noqa: FBT001, FBT002 - FastMCP exposes keyword args.
        facets: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            return _to_json_object(await gateway_client.find_targets({
                "filter": dict(filter),
                "limit": limit,
                "dry_run": dry_run,
                "facets": list(facets or []),
            }))
        except LoginRequired as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="run_remote_tool",
        description="Run one remote tool against a target_handle returned by find_targets.",
        structured_output=True,
    )
    async def run_remote_tool(
        tool_name: str,
        target_handle: str,
        arguments: dict[str, Any] | None = None,
        max_nodes: int = 100,
        max_concurrency: int = 8,
    ) -> dict[str, Any]:
        try:
            return _to_json_object(await gateway_client.run_remote_tool({
                "tool_name": tool_name,
                "target_handle": target_handle,
                "arguments": dict(arguments or {}),
                "max_nodes": max_nodes,
                "max_concurrency": max_concurrency,
            }))
        except LoginRequired as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="get_remote_run",
        description="Return one page of remote run results.",
        structured_output=True,
    )
    async def get_remote_run(
        run_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        try:
            return _to_json_object(await gateway_client.get_remote_run({
                "run_id": run_id,
                "offset": offset,
                "limit": limit,
            }))
        except LoginRequired as exc:
            raise ToolError(str(exc)) from exc

    return server


def _to_jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True, mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_to_jsonable(item) for item in value]
    return value


def _to_json_object(value: object) -> dict[str, Any]:
    converted = _to_jsonable(value)
    if isinstance(converted, dict):
        return converted
    return {"result": converted}
