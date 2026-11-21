from abc import ABC, abstractmethod
from decimal import Decimal
import re
from typing import List, Optional, Tuple
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct


def normalize_piece_unit_price(
    name: str,
    textual_amount: str,
    price: Decimal,
    unit_type: UnitType,
    unit_price: Optional[Decimal],
) -> Tuple[UnitType, Optional[Decimal]]:
    """Convert piece-priced produce/goods to per-kg or per-l when approximate weight/volume is present."""
    if unit_type not in (UnitType.PIECE, UnitType.UNKNOWN) or price <= 0:
        return unit_type, unit_price

    haystack = f"{name} {textual_amount}".lower()
    # Match e.g. "(cca 260 g)", "cca 900g", "500 ml", "1,5 l", "0.5 kg"
    match = re.search(r"(?:cca\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", haystack)
    if not match:
        return unit_type, unit_price

    qty = Decimal(match.group(1).replace(",", "."))
    unit = match.group(2)
    if qty <= 0:
        return unit_type, unit_price

    if unit == "g":
        kg = qty / Decimal("1000")
        return UnitType.KILOGRAM, round(price / kg, 2)
    if unit == "kg":
        return UnitType.KILOGRAM, round(price / qty, 2)
    if unit == "ml":
        liters = qty / Decimal("1000")
        return UnitType.LITER, round(price / liters, 2)
    if unit == "l":
        return UnitType.LITER, round(price / qty, 2)
    return unit_type, unit_price


class BaseStoreClient(ABC):
    """Abstract base class for grocery store clients."""

    @property
    @abstractmethod
    def store_type(self) -> StoreType:
        """Return the store identifier."""
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> List[StoreProduct]:
        """Search products on the store and return normalized StoreProduct list.
        
        Args:
            query: Product search query string in Czech.
            limit: Maximum number of products to return.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, product_id: str) -> Optional[StoreProduct]:
        """Fetch details of a single product by store product id."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify store availability."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Clean up underlying HTTP sessions or resources."""
        raise NotImplementedError
