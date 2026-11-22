"""Backfill and annotate cached translations using Gemini 3.5 Flash into Langfuse."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_monitoring_service, get_translation_cache
from app.services.llm import GeminiLLMService
from app.services.translation_dataset import backfill_and_annotate_translations


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Annotate translations with Gemini and store in Langfuse")
    parser.add_argument("--limit", type=int, default=25, help="Max translations to annotate (0 for all)")
    args = parser.parse_args()

    monitoring = get_monitoring_service()
    cache = get_translation_cache()
    llm = GeminiLLMService(monitoring=monitoring)

    result = await backfill_and_annotate_translations(
        cache_service=cache,
        llm=llm,
        monitoring=monitoring,
        limit=args.limit if args.limit > 0 else None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_main())
