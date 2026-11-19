import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from app.api.deps import get_comparison_service
from app.models.voice import GoogleHomeVoiceResponse, IFTTTWebhookRequest
from app.services.comparator import PriceComparisonService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ifttt", response_model=GoogleHomeVoiceResponse)
async def ifttt_voice_webhook(
    payload: IFTTTWebhookRequest,
    comparator: PriceComparisonService = Depends(get_comparison_service),
) -> GoogleHomeVoiceResponse:
    """Handle incoming IFTTT Google Assistant routine with text ingredient."""
    query = payload.ingredient.strip()
    logger.info(f"Received IFTTT voice query: '{query}'")

    try:
        comparison = await comparator.compare_single_item(query)
        spoken_text = comparison.voice_summary_en
        return GoogleHomeVoiceResponse(
            message=spoken_text,
            fulfillmentText=spoken_text,
            success=True,
            query=query,
        )
    except Exception as exc:
        logger.error(f"Error handling IFTTT voice request for '{query}': {exc}")
        fallback = f"Sorry, I had trouble checking prices for {query}."
        return GoogleHomeVoiceResponse(
            message=fallback,
            fulfillmentText=fallback,
            success=False,
            query=query,
        )


@router.get("/query", response_model=GoogleHomeVoiceResponse)
async def direct_voice_query(
    q: str = Query(..., min_length=1, description="Spoken product query"),
    lang: Optional[str] = Query(default="en", description="Language preference"),
    comparator: PriceComparisonService = Depends(get_comparison_service),
) -> GoogleHomeVoiceResponse:
    """Quick GET endpoint for testing or simple webhook configurations."""
    query = q.strip()
    comparison = await comparator.compare_single_item(query)
    speech = comparison.voice_summary_cs if lang == "cs" else comparison.voice_summary_en
    return GoogleHomeVoiceResponse(
        message=speech,
        fulfillmentText=speech,
        success=True,
        query=query,
    )
