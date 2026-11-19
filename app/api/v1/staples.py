from typing import List
from fastapi import APIRouter, Depends
from app.api.deps import get_comparison_service
from app.models.staples import StapleDefinition
from app.services.comparator import PriceComparisonService

router = APIRouter()


@router.get("", response_model=List[StapleDefinition])
async def list_staples(
    comparator: PriceComparisonService = Depends(get_comparison_service),
) -> List[StapleDefinition]:
    """Retrieve all configured staple items for 1-click comparison."""
    return comparator.get_all_staples()
