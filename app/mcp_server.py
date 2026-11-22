"""FastMCP server exposing Grocery Price Comparator APIs as MCP tools.

Follows FastMCP best practices:
  - Uses ``FastMCP.from_fastapi()`` to auto-generate typed MCP tools from OpenAPI.
  - Filters out non-API HTML/health/A2A routes via ``RouteMap`` so LLMs only see
    clean, well-documented ``/api/v1/*`` tools.
  - Exposes Streamable HTTP transport via ``mcp.http_app(path="/")`` for mounting
    into FastAPI, and supports standalone execution via ``python -m app.mcp_server``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_mcp_server(
    fastapi_app: FastAPI,
    internal_token: Optional[str] = None,
) -> FastMCP:
    """Build a FastMCP server from the existing FastAPI application."""
    route_maps = [
        # Exclude auth endpoints from LLM tool surface
        RouteMap(pattern=r"^/api/v1/auth/.*", mcp_type=MCPType.EXCLUDE),
        # Strictly read-only: only expose GET endpoints under /api/v1/* (no POST/PUT/PATCH/DELETE)
        RouteMap(methods=["GET"], pattern=r"^/api/v1/.*", mcp_type=MCPType.TOOL),
        # Exclude all non-GET methods and non-/api/v1/ routes
        RouteMap(methods="*", pattern=r".*", mcp_type=MCPType.EXCLUDE),
    ]
    httpx_kwargs = {
        "timeout": 30.0,
        **({"headers": {"X-Internal-MCP-Token": internal_token}} if internal_token else {}),
    }
    return FastMCP.from_fastapi(
        app=fastapi_app,
        name="GroceryPriceComparatorMCP",
        route_maps=route_maps,
        httpx_client_kwargs=httpx_kwargs,
    )


if __name__ == "__main__":
    from app.main import app as fastapi_app

    mcp = create_mcp_server(fastapi_app)
    mcp.run(transport="http", host="127.0.0.1", port=8001)
