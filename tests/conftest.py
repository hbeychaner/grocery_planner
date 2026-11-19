from decimal import Decimal
from typing import List, Optional
import pytest

from app.clients.base import BaseStoreClient
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct


class MockStoreClient(BaseStoreClient):
    """Mock store client for testing."""

    def __init__(self, store_type: StoreType, products: Optional[List[StoreProduct]] = None) -> None:
        self._store_type = store_type
        self.products = products or []

    @property
    def store_type(self) -> StoreType:
        return self._store_type

    async def search(self, query: str, limit: int = 5) -> List[StoreProduct]:
        return self.products[:limit]

    async def get_by_id(self, product_id: str) -> Optional[StoreProduct]:
        for p in self.products:
            if p.product_id == product_id:
                return p
        return None

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        pass


@pytest.fixture
def sample_rohlik_butter() -> StoreProduct:
    return StoreProduct(
        store=StoreType.ROHLIK,
        product_id="r_butter_1",
        name="Jihočeské máslo 250g",
        brand="Madeta",
        price=Decimal("52.90"),
        original_price=Decimal("62.90"),
        is_on_sale=True,
        unit_type=UnitType.GRAM,
        unit_price=Decimal("211.60"),
        package_amount=Decimal("250"),
        in_stock=True,
        url="https://www.rohlik.cz/test-butter",
    )


@pytest.fixture
def sample_kosik_butter() -> StoreProduct:
    return StoreProduct(
        store=StoreType.KOSIK,
        product_id="k_butter_1",
        name="Madeta Jihočeské máslo 250g",
        brand="Madeta",
        price=Decimal("59.90"),
        original_price=None,
        is_on_sale=False,
        unit_type=UnitType.GRAM,
        unit_price=Decimal("239.60"),
        package_amount=Decimal("250"),
        in_stock=True,
        url="https://www.kosik.cz/test-butter",
    )
