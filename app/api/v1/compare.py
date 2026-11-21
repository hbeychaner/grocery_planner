from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.deps import get_comparison_service, get_kupi_client
from app.clients.kupi import KupiClient, KupiDeal
from app.models.comparison import (
    BasketComparisonRequest,
    BasketComparisonResponse,
    ComparisonResponse,
)
from app.services.comparator import PriceComparisonService

router = APIRouter()


@router.get("", response_model=ComparisonResponse)
async def compare_product(
    q: str = Query(..., min_length=1, description="Product query to compare (in English or Czech)"),
    lang: Optional[str] = Query(default="en", description="Preferred response language (en or cs)"),
    comparator: PriceComparisonService = Depends(get_comparison_service),
) -> ComparisonResponse:
    """Compare prices for a single product across Rohlik and Kosik."""
    try:
        result = await comparator.compare_single_item(q)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(exc)}")


@router.post("/basket", response_model=BasketComparisonResponse)
async def compare_basket(
    payload: BasketComparisonRequest,
    comparator: PriceComparisonService = Depends(get_comparison_service),
) -> BasketComparisonResponse:
    """Compare a full shopping basket across both stores."""
    try:
        result = await comparator.compare_basket(payload.items)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Basket comparison failed: {str(exc)}")


@router.get("/kupi", response_model=List[KupiDeal])
async def search_kupi_deals(
    q: str = Query(..., min_length=1, description="Product query to look up across Tesco, Lidl, Penny, Kaufland, Billa, Albert"),
    comparator: PriceComparisonService = Depends(get_comparison_service),
    kupi: KupiClient = Depends(get_kupi_client),
) -> List[KupiDeal]:
    """Fetch active supermarket promotional deals from Kupi.cz."""
    t_res = await comparator.bilingual.translate_query_async(q, ollama_service=comparator.ollama)
    return await kupi.search_deals(t_res.primary_term, limit=12)
