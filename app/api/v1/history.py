from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_price_history_service, get_tracker_runner
from app.services.price_history import (
    CategoryAnalyticsResponse,
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
    history: PriceHistoryService = Depends(get_price_history_service),
) -> CategoryAnalyticsResponse:
    """Return overall and per-category average unit prices and weekly inflation metrics."""
    return history.get_category_analytics()


@router.get("/items", response_model=TrackedItemsListResponse)
async def list_tracked_items(
    history: PriceHistoryService = Depends(get_price_history_service),
) -> TrackedItemsListResponse:
    """List all tracked groceries and their latest recorded unit prices."""
    return TrackedItemsListResponse(
        stats=history.get_stats(),
        items=history.list_tracked_items(active_only=True),
    )


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
