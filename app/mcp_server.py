"""FastMCP server exposing Grocery Price Comparator APIs as MCP tools.

Follows FastMCP best practices:
  - Uses ``FastMCP.from_fastapi()`` to auto-generate typed MCP tools from OpenAPI.
  - Filters out non-API HTML/health/A2A routes via ``RouteMap`` so LLMs only see
    clean, well-documented ``/api/v1/*`` tools.
  - Exposes Streamable HTTP transport via ``mcp.http_app(path="/")`` for mounting
    into FastAPI, and supports standalone execution via ``python -m app.mcp_server``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_mcp_server(fastapi_app: FastAPI) -> FastMCP:
    """Build a FastMCP server from the existing FastAPI application."""
    route_maps = [
        # Expose all /api/v1/* endpoints as MCP tools
        RouteMap(pattern=r"^/api/v1/.*", mcp_type=MCPType.TOOL),
        # Exclude UI, health, A2A, and docs routes from MCP tool surface
        RouteMap(pattern=r"^/(?!api/v1/).*", mcp_type=MCPType.EXCLUDE),
    ]
    return FastMCP.from_fastapi(
        app=fastapi_app,
        name="GroceryPriceComparatorMCP",
        route_maps=route_maps,
    )


if __name__ == "__main__":
    from app.main import app as fastapi_app

    mcp = create_mcp_server(fastapi_app)
    mcp.run(transport="http", host="127.0.0.1", port=8001)
