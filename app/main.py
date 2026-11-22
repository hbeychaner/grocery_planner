import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
import os
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
    get_tracker_runner,
    get_translation_cache,
)
from app.api.v1.auth import google_oauth_router
from app.api.v1.router import api_v1_router
from app.a2a_agent import mount_a2a_agent
from app.core.config import settings
from app.mcp_server import create_mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for connection pools, MCP session manager, daily tracker, and monitoring."""
    logger = logging.getLogger(__name__)
    tracker_task: asyncio.Task[None] | None = None

    async def _daily_tracker_loop() -> None:
        await asyncio.sleep(5)
        while True:
            try:
                history = get_price_history_service()
                last_ts = history.get_latest_store_snapshot_at()
                now_utc = datetime.now(timezone.utc)
                if last_ts is None or (now_utc - last_ts) >= timedelta(hours=20):
                    logger.info("Starting daily price & discount tracker sweep...")
                    result = await get_tracker_runner().run()
                    logger.info(
                        "Daily tracker sweep finished: %d/%d items, %d snapshots in %.1fs",
                        result.succeeded,
                        result.total_items,
                        result.snapshots_recorded,
                        result.duration_seconds,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"Daily tracker loop error: {exc}")
            await asyncio.sleep(24 * 60 * 60)

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        tracker_task = asyncio.create_task(_daily_tracker_loop())

    async with mcp_app.lifespan(app):
        yield

    if tracker_task is not None:
        tracker_task.cancel()
        try:
            await tracker_task
        except asyncio.CancelledError:
            pass
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


_INTERNAL_MCP_TOKEN = secrets.token_urlsafe(32)
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

    # Require authenticated session (or API token) for protected API & A2A routes when enabled
    if settings.require_auth and (
        path.startswith("/api/v1/compare")
        or path.startswith("/api/v1/discounts")
        or path.startswith("/api/v1/history")
        or path.startswith("/api/v1/staples")
        or path.startswith("/a2a")
    ):
        mcp_tok = request.headers.get("X-Internal-MCP-Token", "")
        has_internal_mcp = bool(mcp_tok and secrets.compare_digest(mcp_tok, _INTERNAL_MCP_TOKEN))
        session_cookie = request.cookies.get("gp_session")
        user = get_auth_service().get_user_by_session(session_cookie)
        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        api_key = request.headers.get("X-API-Key", "")
        provided_tok = bearer or api_key
        has_api_token = bool(
            settings.api_auth_token
            and provided_tok
            and secrets.compare_digest(provided_tok, settings.api_auth_token)
        )
        if user is None and not has_api_token and not has_internal_mcp:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})

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

    if path.startswith("/static") or path in ("/", "/trends", "/discounts"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Mount static assets and built React SPA assets
static_dir = settings.base_dir / "static"
frontend_dist_dir = settings.base_dir / "frontend" / "dist"
if (frontend_dist_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist_dir / "assets")), name="frontend-assets")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include API v1 router and Google OAuth routes
app.include_router(api_v1_router)
app.include_router(google_oauth_router)

# Build and mount FastMCP server (exposing /api/v1/* as MCP tools at /mcp)
mcp_server = create_mcp_server(app, internal_token=_INTERNAL_MCP_TOKEN)
mcp_app = mcp_server.http_app(path="/")
app.mount("/mcp", mcp_app)

# Mount A2A-compliant agent (/.well-known/agent-card.json, /a2a, /a2a/rest)
mount_a2a_agent(
    app,
    mcp_target=settings.mcp_server_url or mcp_server,
)


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serve the React SPA (or legacy static fallback)."""
    spa_index = frontend_dist_dir / "index.html"
    return FileResponse(spa_index if spa_index.exists() else (static_dir / "index.html"))


@app.get("/trends", include_in_schema=False)
async def serve_trends() -> FileResponse:
    """Serve the React SPA trends route (or legacy static fallback)."""
    spa_index = frontend_dist_dir / "index.html"
    return FileResponse(spa_index if spa_index.exists() else (static_dir / "trends.html"))


@app.get("/discounts", include_in_schema=False)
async def serve_discounts() -> FileResponse:
    """Serve the React SPA discounts route."""
    spa_index = frontend_dist_dir / "index.html"
    return FileResponse(spa_index if spa_index.exists() else (static_dir / "index.html"))


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
