"""Run a Langfuse Experiment evaluating relevance classifiers against captured data."""

import argparse
import asyncio
from decimal import Decimal
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_monitoring_service
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct
from app.services.llm import create_llm_service
from app.services.matcher import ProductMatchingService
from app.services.relevance_dataset import run_relevance_experiment


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate grocery relevance classifiers via Langfuse Experiments")
    parser.add_argument(
        "--provider",
        choices=["spacy-minilm", "ollama", "gemini"],
        default="spacy-minilm",
        help="Classifier to evaluate",
    )
    parser.add_argument("--experiment", default="relevance-classifier-eval", help="Langfuse experiment name")
    parser.add_argument("--max-items", type=int, default=50, help="Maximum dataset items to evaluate")
    args = parser.parse_args()

    monitoring = get_monitoring_service()

    if args.provider == "spacy-minilm":
        matcher = ProductMatchingService()

        async def _predict(query: str, query_cs: str, titles: List[str]) -> List[int]:
            prods = [
                StoreProduct(
                    store=StoreType.ROHLIK,
                    product_id=str(i),
                    name=t,
                    price=Decimal("10.00"),
                    unit_type=UnitType.KILOGRAM,
                    unit_price=Decimal("10.00"),
                    in_stock=True,
                )
                for i, t in enumerate(titles)
            ]
            kept = matcher._filter_relevant_products(query_cs or query, prods, query)
            kept_ids = {int(p.product_id) for p in kept}
            return sorted(kept_ids)

        predictor = _predict
    else:
        llm = create_llm_service(args.provider, monitoring=monitoring)

        async def _predict_llm(query: str, query_cs: str, titles: List[str]) -> List[int]:
            res = await llm.filter_relevant_indices(query, titles, query_cs=query_cs)
            return res if res is not None else []

        predictor = _predict_llm

    summary = await run_relevance_experiment(
        experiment_name=args.experiment,
        run_name=f"{args.provider}",
        predictor=predictor,
        monitoring=monitoring,
        max_items=args.max_items,
    )
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
