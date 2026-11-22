from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_bls_service, get_csu_service, get_price_history_service, get_tracker_runner
from app.services.bls_client import BlsIngestResult, BlsPriceIngestionService
from app.services.csu_client import CsuIngestResult, CsuPriceIngestionService
from app.services.price_history import (
    CategoryAnalyticsResponse,
    CategoryHistorySeries,
    ItemPriceHistory,
    PriceHistoryService,
    PriceHistoryStats,
    TrackedItem,
)
from app.services.tracker_runner import PriceTrackerRunner, TrackerRunResult

router = APIRouter()


class AddTrackedItemRequest(BaseModel):
    """Payload to add a grocery item to the weekly watchlist."""

    query: str = Field(..., min_length=1, description="Grocery item query")
    category: Optional[str] = Field(default=None, description="Optional category")


class TrackedItemsListResponse(BaseModel):
    """Watchlist and aggregate statistics."""

    stats: PriceHistoryStats
    items: list[TrackedItem]


@router.get("/analytics", response_model=CategoryAnalyticsResponse)
async def get_category_analytics(
    mode: str = Query(
        default="generic",
        pattern="^(generic|comparison)$",
        description="Analytics aggregation mode: 'generic' (all items) or 'comparison' (matched basket across all sources)",
    ),
    normalize_by_income: bool = Query(
        default=False,
        description="Normalize prices by monthly median income of Czechia vs. Midwest USA (% of monthly median income)",
    ),
    history: PriceHistoryService = Depends(get_price_history_service),
) -> CategoryAnalyticsResponse:
    """Return overall and per-category average unit prices and weekly inflation metrics."""
    return history.get_category_analytics(mode=mode, normalize_by_income=normalize_by_income)


@router.get("/analytics/series", response_model=CategoryHistorySeries)
async def get_category_series(
    category: str = Query(default="overall", description="Category slug or 'overall'"),
    days: int = Query(default=90, ge=1, le=3650, description="Lookback window in days"),
    mode: str = Query(
        default="generic",
        pattern="^(generic|comparison)$",
        description="Analytics aggregation mode: 'generic' (all items) or 'comparison' (matched basket across all sources)",
    ),
    normalize_by_income: bool = Query(
        default=False,
        description="Normalize time series by monthly median income of Czechia vs. Midwest USA (% of monthly median income)",
    ),
    rebase_index: bool = Query(
        default=False,
        description="Rebase each series to Base = 100 at the first available month for relative inflation comparison",
    ),
    granularity: str = Query(
        default="daily",
        pattern="^(daily|monthly)$",
        description="Time bucket granularity: 'daily' (captures daily sales pricing) or 'monthly'",
    ),
    history: PriceHistoryService = Depends(get_price_history_service),
) -> CategoryHistorySeries:
    """Return time-series average unit prices for a category or overall."""
    return history.get_category_series(
        category=category,
        days=days,
        mode=mode,
        normalize_by_income=normalize_by_income,
        rebase_index=rebase_index,
        granularity=granularity,
    )


@router.get("/items", response_model=TrackedItemsListResponse)
async def list_tracked_items(
    history: PriceHistoryService = Depends(get_price_history_service),
) -> TrackedItemsListResponse:
    """List all tracked groceries and their latest recorded unit prices."""
    return TrackedItemsListResponse(
        stats=history.get_stats(),
        items=history.list_tracked_items(active_only=True),
    )


@router.get("/items/search", response_model=list[TrackedItem])
async def search_tracked_items(
    q: str = Query(default="", description="Search query (accent-insensitive + semantic ranking)"),
    category: Optional[str] = Query(default=None, description="Optional category filter"),
    history: PriceHistoryService = Depends(get_price_history_service),
) -> list[TrackedItem]:
    """Return tracked items ranked by accent-insensitive lexical and semantic similarity."""
    return history.rank_tracked_items(query=q, category=category)


@router.post("/items", response_model=TrackedItem)
async def add_tracked_item(
    payload: AddTrackedItemRequest,
    history: PriceHistoryService = Depends(get_price_history_service),
) -> TrackedItem:
    """Add a grocery item to the weekly price tracking watchlist."""
    return history.add_tracked_item(query=payload.query, category=payload.category)


@router.delete("/items/{query}")
async def remove_tracked_item(
    query: str,
    history: PriceHistoryService = Depends(get_price_history_service),
) -> dict[str, bool]:
    """Remove a grocery item from the active watchlist."""
    removed = history.remove_tracked_item(query)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Tracked item '{query}' not found")
    return {"removed": True}


@router.get("/series", response_model=ItemPriceHistory)
async def get_item_price_series(
    q: str = Query(..., min_length=1, description="Tracked grocery item query"),
    days: int = Query(default=90, ge=1, le=3650, description="Lookback window in days"),
    history: PriceHistoryService = Depends(get_price_history_service),
) -> ItemPriceHistory:
    """Return time-series normalized unit-price points for plotting."""
    return history.get_item_history(query=q, days=days)


@router.post("/run", response_model=TrackerRunResult)
async def trigger_price_check(
    limit: Optional[int] = Query(default=None, ge=1, description="Optional cap on items checked"),
    runner: PriceTrackerRunner = Depends(get_tracker_runner),
) -> TrackerRunResult:
    """Run an on-demand price-check sweep across tracked grocery items."""
    return await runner.run(limit=limit)


@router.post("/ingest-csu", response_model=CsuIngestResult)
async def ingest_csu_history(
    csu: CsuPriceIngestionService = Depends(get_csu_service),
) -> CsuIngestResult:
    """Fetch and pair historical monthly Czech national averages from ČSÚ DataStat API."""
    return await csu.ingest_all()


@router.post("/ingest-bls", response_model=BlsIngestResult)
async def ingest_bls_history(
    bls: BlsPriceIngestionService = Depends(get_bls_service),
) -> BlsIngestResult:
    """Fetch U.S. BLS average food prices converted to CZK via historical USD->CZK rates."""
    return await bls.ingest_all()
