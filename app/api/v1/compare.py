from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.deps import get_comparison_service
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
