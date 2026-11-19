from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import get_kosik_client, get_rohlik_client
from app.api.v1.router import api_v1_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for connection pools."""
    yield
    # Cleanup clients on shutdown
    rohlik = get_rohlik_client()
    kosik = get_kosik_client()
    await rohlik.close()
    await kosik.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Real-time grocery price comparator between Rohlík.cz and Košík.cz with Google Home voice API & Web UI.",
    lifespan=lifespan,
)

# Mount static assets
static_dir = settings.base_dir / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include API v1 router
app.include_router(api_v1_router)


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serve the lightweight web application UI."""
    index_file = static_dir / "index.html"
    return FileResponse(index_file)


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, object]:
    """Service health check verifying stores reachability."""
    rohlik = get_rohlik_client()
    kosik = get_kosik_client()

    rohlik_status = await rohlik.health_check()
    kosik_status = await kosik.health_check()

    return {
        "status": "healthy" if (rohlik_status or kosik_status) else "degraded",
        "rohlik_connected": rohlik_status,
        "kosik_connected": kosik_status,
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
