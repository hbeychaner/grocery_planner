from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class StapleDefinition(BaseModel):
    """Configuration definition of a canonical staple grocery item."""

    id: str = Field(..., description="Unique slug for the staple")
    name_en: str = Field(..., description="English title")
    name_cs: str = Field(..., description="Czech title")
    category: str = Field(default="general", description="Grocery category")
    rohlik_query: str = Field(..., description="Target search query for Rohlik")
    kosik_query: str = Field(..., description="Target search query for Kosik")
    keywords: List[str] = Field(default_factory=list, description="Associated lookup keywords")
    labels: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Language-keyed descriptive labels (e.g. {'en': [...], 'cs': [...]})",
    )


class StaplesCatalog(BaseModel):
    """Collection of configured staples."""

    staples: List[StapleDefinition] = Field(default_factory=list)
