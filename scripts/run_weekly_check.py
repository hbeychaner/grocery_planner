"""Weekly CLI routine to check prices across all tracked groceries and store unit-price history.

Usage:
    ./.venv/bin/python -m scripts.run_weekly_check
    ./.venv/bin/python -m scripts.run_weekly_check --limit 10
"""

import argparse
import asyncio
import logging

from app.api.deps import (
    get_comparison_service,
    get_kosik_client,
    get_monitoring_service,
    get_ollama_service,
    get_price_history_service,
    get_rohlik_client,
    get_translation_cache,
)
from app.services.tracker_runner import PriceTrackerRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main(limit: int | None = None, concurrency: int = 4) -> None:
    comparator = get_comparison_service()
    history = get_price_history_service()
    runner = PriceTrackerRunner(
        comparator=comparator,
        history=history,
        concurrency=concurrency,
    )

    try:
        logger.info("Starting weekly grocery price check...")
        result = await runner.run(limit=limit)
        logger.info(
            "Weekly price check complete: %d/%d succeeded (%d failed), %d snapshots recorded in %.2fs",
            result.succeeded,
            result.total_items,
            result.failed,
            result.snapshots_recorded,
            result.duration_seconds,
        )
    finally:
        await get_rohlik_client().close()
        await get_kosik_client().close()
        await get_ollama_service().close()
        get_translation_cache().close()
        history.close()
        get_monitoring_service().shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run weekly grocery price tracking sweep.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of items checked")
    parser.add_argument("--concurrency", type=int, default=4, help="Max concurrent item checks")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, concurrency=args.concurrency))
