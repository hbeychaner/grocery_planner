from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field
from app.models.enums import StoreType, UnitType


class ProductSale(BaseModel):
    """Individual promotional or clearance discount attached to a store product."""

    sale_type: str = Field(..., description="Sale category (e.g. 'premium', 'sale', 'expiration')")
    price: Decimal = Field(..., ge=0, description="Discounted price in CZK")
    original_price: Optional[Decimal] = Field(default=None, ge=0, description="Original price before discount")
    unit_price: Optional[Decimal] = Field(default=None, ge=0, description="Discounted unit price in CZK")
    discount_percentage: Optional[int] = Field(default=None, ge=0, le=100, description="Discount percentage")
    started_at: Optional[str] = Field(default=None, description="ISO/timestamp when the discount started")
    ends_at: Optional[str] = Field(default=None, description="ISO/timestamp when the discount ends")
    remaining: Optional[int] = Field(default=None, ge=0, description="Remaining discounted units if limited")
    welcome_price: bool = Field(default=False, description="Whether this is a personalized/welcome price")
    unlimited_amount: bool = Field(default=False, description="Whether purchase quantity is unlimited")


class StoreProduct(BaseModel):
    """Normalized store product listing."""

    store: StoreType = Field(..., description="Store where the product is listed")
    product_id: str = Field(..., description="Unique product identifier in the store")
    name: str = Field(..., description="Full display name of the product")
    brand: Optional[str] = Field(default=None, description="Brand name if identified")
    price: Decimal = Field(..., ge=0, description="Current purchase price in CZK")
    original_price: Optional[Decimal] = Field(default=None, ge=0, description="Regular price if on sale")
    is_on_sale: bool = Field(default=False, description="Whether this product currently has a promotional discount")
    discount_percentage: Optional[int] = Field(default=None, ge=0, le=100, description="Active discount percentage")
    sale_type: Optional[str] = Field(default=None, description="Primary active sale type")
    sale_ends_at: Optional[str] = Field(default=None, description="Expiration timestamp of the primary active sale")
    sales: List[ProductSale] = Field(default_factory=list, description="All active discounts on this product")
    unit_type: UnitType = Field(default=UnitType.UNKNOWN, description="Base physical measurement unit")
    unit_price: Optional[Decimal] = Field(default=None, ge=0, description="Normalized price per base unit (e.g. per 1kg or 1L)")
    package_amount: Optional[Decimal] = Field(default=None, gt=0, description="Net weight/volume in the base unit")
    in_stock: bool = Field(default=True, description="Whether the product is currently in stock for delivery")
    url: Optional[str] = Field(default=None, description="Direct web link to product on store website")
    image_url: Optional[str] = Field(default=None, description="Thumbnail/preview image URL")

    @property
    def savings_amount(self) -> Decimal:
        """Calculate discount savings if on sale."""
        if self.is_on_sale and self.original_price and self.original_price > self.price:
            return self.original_price - self.price
        return Decimal("0.00")
