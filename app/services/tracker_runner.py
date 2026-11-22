import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from pydantic import BaseModel

from app.models.product import StoreProduct
from app.services.comparator import PriceComparisonService
from app.services.price_history import PriceHistoryService

logger = logging.getLogger(__name__)


class TrackerRunResult(BaseModel):
    """Summary of a batch price-tracking sweep."""

    total_items: int
    succeeded: int
    failed: int
    snapshots_recorded: int
    duration_seconds: float
    started_at: str
    finished_at: str


class PriceTrackerRunner:
    """Runs bounded-concurrency price checks across all tracked grocery items."""

    def __init__(
        self,
        comparator: PriceComparisonService,
        history: PriceHistoryService,
        concurrency: int = 4,
        delay_between_requests: float = 0.25,
    ) -> None:
        self.comparator = comparator
        self.history = history
        self.concurrency = concurrency
        self.delay_between_requests = delay_between_requests
        self._run_lock = asyncio.Lock()

    async def run(self, limit: Optional[int] = None) -> TrackerRunResult:
        """Fetch current prices for active tracked items and record unit-price snapshots."""
        async with self._run_lock:
            return await self._run_locked(limit=limit)

    async def _run_locked(self, limit: Optional[int] = None) -> TrackerRunResult:
        started_dt = datetime.now(timezone.utc)
        t0 = time.monotonic()

        items = self.history.list_tracked_items(active_only=True)
        if limit is not None and limit > 0:
            items = items[:limit]
        category_by_query = {item.query: item.category for item in items}

        semaphore = asyncio.Semaphore(self.concurrency)
        succeeded = 0
        failed = 0
        snapshots_recorded = 0
        discounted_products: List[Tuple[str, Optional[str], StoreProduct]] = []

        async def _check_one(query: str) -> None:
            nonlocal succeeded, failed, snapshots_recorded
            async with semaphore:
                try:
                    comparison = await self.comparator.compare_single_item(query)
                    count = self.history.record_comparison(comparison, recorded_at=started_dt)
                    snapshots_recorded += count
                    cat = category_by_query.get(query)
                    for cand in (*comparison.rohlik_candidates, *comparison.kosik_candidates):
                        if cand.is_on_sale or cand.sales:
                            discounted_products.append((query, cat, cand))
                    succeeded += 1
                    done = succeeded + failed
                    if done % 20 == 0 or done == len(items):
                        logger.info(
                            "Tracker progress: %d/%d items (%d snapshots recorded)",
                            done,
                            len(items),
                            snapshots_recorded,
                        )
                except Exception as exc:
                    failed += 1
                    logger.warning(f"Price check failed for '{query}': {exc}")
                if self.delay_between_requests > 0:
                    await asyncio.sleep(self.delay_between_requests)

        await asyncio.gather(*(_check_one(item.query) for item in items))

        if discounted_products and limit is None:
            self.history.save_discount_snapshots(discounted_products, scanned_at=started_dt)

        finished_dt = datetime.now(timezone.utc)
        return TrackerRunResult(
            total_items=len(items),
            succeeded=succeeded,
            failed=failed,
            snapshots_recorded=snapshots_recorded,
            duration_seconds=round(time.monotonic() - t0, 2),
            started_at=started_dt.isoformat(),
            finished_at=finished_dt.isoformat(),
        )
