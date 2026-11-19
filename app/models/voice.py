from typing import Optional
from pydantic import BaseModel, Field


class IFTTTWebhookRequest(BaseModel):
    """Payload received from IFTTT Google Assistant routine with text ingredient."""

    ingredient: str = Field(..., min_length=1, description="Extracted voice text (e.g. 'butter' or 'whole milk')")
    device_id: Optional[str] = Field(default="google_home", description="Originating device identifier")


class GoogleHomeVoiceResponse(BaseModel):
    """Voice fulfillment response for Google Home / IFTTT."""

    message: str = Field(..., description="Spoken message response in English")
    fulfillmentText: str = Field(..., description="Assistant speech field")
    success: bool = Field(default=True, description="Execution success flag")
    query: str = Field(..., description="Query processed")
