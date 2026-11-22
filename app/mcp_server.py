"""FastMCP server exposing Grocery Price Comparator APIs as MCP tools.

Follows FastMCP best practices:
  - Uses ``FastMCP.from_fastapi()`` to auto-generate typed MCP tools from OpenAPI.
  - Filters out non-API HTML/health/A2A routes via ``RouteMap`` so LLMs only see
    clean, well-documented ``/api/v1/*`` tools.
  - Exposes Streamable HTTP transport via ``mcp.http_app(path="/")`` for mounting
    into FastAPI, and supports standalone execution via ``python -m app.mcp_server``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.providers.openapi import MCPType, RouteMap

from app.services.auth import OBO_AUDIENCE, OBO_DEFAULT_SCOPES, OBO_ISSUER

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_mcp_server(
    fastapi_app: FastAPI,
    internal_token: Optional[str] = None,
    obo_public_key_pem: Optional[str] = None,
) -> FastMCP:
    """Build a read-only FastMCP server from the FastAPI app with optional OBO JWTVerifier."""
    route_maps = [
        # Exclude auth endpoints from LLM tool surface
        RouteMap(pattern=r"^/api/v1/auth/.*", mcp_type=MCPType.EXCLUDE),
        # Strictly read-only: only expose GET endpoints under /api/v1/* (no POST/PUT/PATCH/DELETE)
        RouteMap(methods=["GET"], pattern=r"^/api/v1/.*", mcp_type=MCPType.TOOL),
        # Exclude all non-GET methods and non-/api/v1/ routes
        RouteMap(methods="*", pattern=r".*", mcp_type=MCPType.EXCLUDE),
    ]

    async def _forward_obo_auth(request: httpx.Request) -> None:
        tok = get_access_token()
        if tok is not None and getattr(tok, "token", None):
            request.headers["Authorization"] = f"Bearer {tok.token}"
        elif internal_token:
            request.headers["X-Internal-MCP-Token"] = internal_token

    httpx_kwargs: dict[str, Any] = {
        "timeout": 30.0,
        "event_hooks": {"request": [_forward_obo_auth]},
    }
    if internal_token:
        httpx_kwargs["headers"] = {"X-Internal-MCP-Token": internal_token}

    auth_provider = (
        JWTVerifier(
            public_key=obo_public_key_pem,
            issuer=OBO_ISSUER,
            audience=OBO_AUDIENCE,
            algorithm="RS256",
            required_scopes=OBO_DEFAULT_SCOPES,
        )
        if obo_public_key_pem
        else None
    )

    return FastMCP.from_fastapi(
        app=fastapi_app,
        name="GroceryPriceComparatorMCP",
        route_maps=route_maps,
        httpx_client_kwargs=httpx_kwargs,
        auth=auth_provider,
    )


if __name__ == "__main__":
    from app.main import app as fastapi_app

    mcp = create_mcp_server(fastapi_app)
    mcp.run(transport="http", host="127.0.0.1", port=8001)
