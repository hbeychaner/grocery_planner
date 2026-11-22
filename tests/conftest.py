from decimal import Decimal
from pathlib import Path
from typing import List, Optional
import pytest

from app.api import deps
from app.clients.base import BaseStoreClient
from app.core.config import settings
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct


@pytest.fixture(autouse=True)
def _isolate_test_telemetry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent unit tests from writing test items to live Langfuse or data/relevance_training.jsonl."""
    monkeypatch.setattr(settings, "langfuse_enabled", False)
    monkeypatch.setattr(settings, "require_auth", False)
    monkeypatch.setattr(settings, "relevance_dataset_path", tmp_path / "relevance_training.jsonl")
    monkeypatch.setattr(deps._monitoring_service, "enabled", False)
    monkeypatch.setattr(deps._monitoring_service, "_client", None)


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
