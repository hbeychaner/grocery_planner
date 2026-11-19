from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field
from app.models.enums import PriceAdvantage, StoreType
from app.models.product import StoreProduct


class MatchedProductPair(BaseModel):
    """Pair of matched products across Rohlik and Kosik for comparison."""

    query: str = Field(..., description="Original search keyword")
    query_cs: str = Field(..., description="Czech search term used for querying store catalogs")
    rohlik_product: Optional[StoreProduct] = Field(default=None, description="Matched Rohlik item")
    kosik_product: Optional[StoreProduct] = Field(default=None, description="Matched Kosik item")
    advantage: PriceAdvantage = Field(..., description="Outcome of the price comparison")
    cheaper_store: Optional[StoreType] = Field(default=None, description="Which store is cheaper, if any")
    price_difference: Decimal = Field(default=Decimal("0.00"), description="Absolute price difference in CZK")
    percentage_savings: Decimal = Field(default=Decimal("0.0"), description="Percentage saved by choosing the cheaper store")
    match_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Product title matching confidence score")


class ComparisonResponse(BaseModel):
    """Full API comparison response for a single query or list of items."""

    query: str = Field(..., description="Original requested search term")
    query_translated: str = Field(..., description="Czech translated term used to query catalogs")
    advantage: PriceAdvantage = Field(..., description="Overall winner or tie")
    cheapest_store: Optional[StoreType] = Field(default=None, description="Cheapest store name")
    price_difference: Decimal = Field(default=Decimal("0.00"), description="Price difference in CZK")
    percentage_savings: Decimal = Field(default=Decimal("0.0"), description="Savings percentage")
    voice_summary_en: str = Field(..., description="Voice-optimized English summary suitable for Google Home speech")
    voice_summary_cs: str = Field(..., description="Voice-optimized Czech summary")
    primary_pair: Optional[MatchedProductPair] = Field(default=None, description="Top matched pair")
    all_pairs: List[MatchedProductPair] = Field(default_factory=list, description="All compared candidate pairs")
    rohlik_candidates: List[StoreProduct] = Field(default_factory=list, description="Top Rohlik search results")
    kosik_candidates: List[StoreProduct] = Field(default_factory=list, description="Top Kosik search results")


class BasketComparisonItem(BaseModel):
    """Individual item for multi-product basket comparison."""

    query: str = Field(..., description="Name of the grocery item")
    quantity: int = Field(default=1, ge=1, description="Quantity needed")


class BasketComparisonRequest(BaseModel):
    """Request payload for comparing an entire shopping list."""

    items: List[BasketComparisonItem] = Field(..., min_length=1, description="List of grocery items to compare")


class BasketComparisonResponse(BaseModel):
    """Comparison response for an entire multi-item grocery basket."""

    total_rohlik: Decimal = Field(..., description="Total price on Rohlik in CZK")
    total_kosik: Decimal = Field(..., description="Total price on Kosik in CZK")
    advantage: PriceAdvantage = Field(..., description="Which store offers the cheaper overall basket")
    cheapest_store: Optional[StoreType] = Field(default=None)
    savings: Decimal = Field(..., description="Total amount saved in CZK by ordering from the winning store")
    percentage_savings: Decimal = Field(..., description="Basket savings percentage")
    voice_summary_en: str = Field(..., description="Spoken summary for Google Home")
    items: List[MatchedProductPair] = Field(default_factory=list, description="Detailed comparison per item")
