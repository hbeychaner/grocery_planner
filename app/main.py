from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import time
from typing import Any, AsyncGenerator, Deque, Dict
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import (
    get_auth_service,
    get_kosik_client,
    get_kupi_client,
    get_monitoring_service,
    get_ollama_service,
    get_price_history_service,
    get_rohlik_client,
    get_translation_cache,
)
from app.api.v1.auth import google_oauth_router
from app.api.v1.router import api_v1_router
from app.a2a_agent import mount_a2a_agent
from app.core.config import settings
from app.mcp_server import create_mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for connection pools, MCP session manager, and monitoring."""
    async with mcp_app.lifespan(app):
        yield
    # Cleanup clients on shutdown
    rohlik = get_rohlik_client()
    kosik = get_kosik_client()
    kupi = get_kupi_client()
    ollama = get_ollama_service()
    monitoring = get_monitoring_service()
    cache = get_translation_cache()
    price_history = get_price_history_service()
    await rohlik.close()
    await kosik.close()
    await kupi.close()
    await ollama.close()
    cache.close()
    price_history.close()
    get_auth_service().close()
    monitoring.shutdown()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Real-time grocery price comparator between Rohlík.cz and Košík.cz with Google Home voice API & Web UI.",
    lifespan=lifespan,
)


_RATE_LIMIT_BUCKETS: Dict[str, Deque[float]] = defaultdict(deque)
_EXPENSIVE_PATHS = (
    "/a2a",
    "/api/v1/compare",
    "/api/v1/history/run",
    "/api/v1/history/ingest-csu",
    "/api/v1/history/ingest-bls",
)
_ADMIN_PATHS = (
    "/api/v1/history/run",
    "/api/v1/history/ingest-csu",
    "/api/v1/history/ingest-bls",
)


@app.middleware("http")
async def security_and_cache_middleware(request: Request, call_next: Any) -> Response:
    """Enforce optional API key on admin mutations, rate limiting, security headers, and dev cache control."""
    path = request.url.path

    # Optional bearer / X-API-Key protection on mutating / ingestion endpoints
    if settings.api_auth_token and (
        path in _ADMIN_PATHS
        or (request.method == "DELETE" and path.startswith("/api/v1/history/items/"))
    ):
        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        api_key = request.headers.get("X-API-Key", "")
        provided = bearer or api_key
        if not provided or not secrets.compare_digest(provided, settings.api_auth_token):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API token"})

    # Sliding-window per-IP rate limiting on expensive / LLM / ingestion endpoints
    if request.method == "POST" and any(path.startswith(p) for p in _EXPENSIVE_PATHS):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        bucket = _RATE_LIMIT_BUCKETS[client_ip]
        while bucket and (now - bucket[0]) > 60.0:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_per_minute:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again shortly."})
        bucket.append(now)

    response = await call_next(request)

    # Security headers (allow Swagger UI inline script on /docs and /redoc)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    script_src = (
        "'self' 'unsafe-inline' https://cdn.jsdelivr.net"
        if path in ("/docs", "/redoc")
        else "'self' https://cdn.jsdelivr.net"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https: data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )

    if path.startswith("/static") or path in ("/", "/trends"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Mount static assets
static_dir = settings.base_dir / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include API v1 router and Google OAuth routes
app.include_router(api_v1_router)
app.include_router(google_oauth_router)

# Build and mount FastMCP server (exposing /api/v1/* as MCP tools at /mcp)
mcp_server = create_mcp_server(app)
mcp_app = mcp_server.http_app(path="/")
app.mount("/mcp", mcp_app)

# Mount A2A-compliant agent (/.well-known/agent-card.json, /a2a, /a2a/rest)
mount_a2a_agent(
    app,
    mcp_target=settings.mcp_server_url or mcp_server,
)


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serve the lightweight web application UI."""
    index_file = static_dir / "index.html"
    return FileResponse(index_file)


@app.get("/trends", include_in_schema=False)
async def serve_trends() -> FileResponse:
    """Serve the price-per-unit history & trends dashboard."""
    trends_file = static_dir / "trends.html"
    return FileResponse(trends_file)


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, object]:
    """Service health check verifying stores and optional Ollama reachability."""
    rohlik = get_rohlik_client()
    kosik = get_kosik_client()
    ollama = get_ollama_service()

    rohlik_status = await rohlik.health_check()
    kosik_status = await kosik.health_check()
    ollama_status = await ollama.health_check()

    return {
        "status": "healthy" if (rohlik_status or kosik_status) else "degraded",
        "rohlik_connected": rohlik_status,
        "kosik_connected": kosik_status,
        "ollama_connected": ollama_status,
        "environment": settings.environment,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
